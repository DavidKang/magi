from builders import PR_ONE, SETTINGS, board, settings_file
from magi.adapters import storage
from magi.tui.board_files import REFRESH_COOLDOWN, REFRESH_SECONDS
from magi.tui.web_watch import TUI_FIRST, watch


class Run:
    """magi web on a fake clock: each sleep moves the clock on, and the one after the last round stops it as ctrl-c does."""

    def __init__(self, cache, rounds, collect=None):
        self.cache, self.rounds = cache, rounds
        self.now, self.sleeps, self.opened, self.said, self.collected = 1000.0, [], [], [], []
        self.collect = collect or self.board
        self.between = lambda: None

    def board(self, settings):
        self.collected.append(self.now)
        return board([PR_ONE])

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if len(self.sleeps) == self.rounds:
            raise KeyboardInterrupt
        self.between()
        self.now += seconds

    def __call__(self):
        return watch(self.collect, cache=self.cache, config_path=self.config, opener=self.opened.append, clock=lambda: self.now,
                     sleep=self.sleep, say=self.said.append)

    @property
    def config(self):
        return self.cache.with_name("config.json")


def page(cache):
    return cache.with_name("board.html")


def test_magi_web_refreshes_the_board_every_interval_and_opens_its_page_once(cache):
    settings_file(cache)
    run = Run(cache, rounds=3)
    assert run() is None, "ctrl-c stops magi web quietly"
    every = REFRESH_SECONDS + TUI_FIRST
    assert run.collected == [1000.0, 1000.0 + every, 1000.0 + 2 * every] and run.sleeps == [every] * 3, \
        "magi web refreshes the board as often as the tui does, a moment late so a running tui's tick goes first"
    assert storage.read(cache)["at"] == 1000.0 + 2 * every, "each refresh is saved where the tui keeps its board, so the tui starts on it"
    assert float(cache.with_name("last-refresh").read_text()) == 1000.0 + 2 * every, \
        "each refresh is marked as it starts, as the tui marks its own, so a tui opened meanwhile waits for it"
    assert f'data-at="{int(1000 + 2 * every) * 1000}"' in page(cache).read_text(), "each refresh rewrites the page, which reloads on it"
    assert run.opened == [str(page(cache))], "the page opens in the browser once, then reloads itself"
    assert any("ctrl-c" in line for line in run.said), "magi web says how to stop it"


def test_magi_web_leaves_the_refresh_to_a_running_tui(cache):
    settings_file(cache)
    storage.write(cache, {"at": 900.0, "board": board([PR_ONE])})
    run = Run(cache, rounds=1)
    run()
    assert run.collected == [], "a board the tui refreshed less than an interval ago is not fetched again"
    assert run.sleeps == [REFRESH_SECONDS + TUI_FIRST - 100] and run.opened == [str(page(cache))], \
        "magi web opens the page on the tui's board and waits until it is due"


def test_a_failed_refresh_is_told_and_tried_again_an_interval_later(cache):
    settings_file(cache)
    attempts = []

    def flaky(settings):
        attempts.append(settings)
        if len(attempts) == 1:
            raise RuntimeError("gh: rate limited")
        return board([PR_ONE])

    run = Run(cache, rounds=2, collect=flaky)
    run()
    assert "refresh failed: gh: rate limited" in run.said, "a failed refresh says why"
    assert len(attempts) == 2 and run.sleeps == [REFRESH_SECONDS + TUI_FIRST] * 2, "and magi web tries again an interval later instead of stopping"
    assert run.opened == [str(page(cache))], "the page opens once there is a board to show"


def test_magi_web_waits_for_a_refresh_a_running_tui_has_started(cache):
    settings_file(cache)
    storage.write(cache, {"at": 700.0, "board": board([PR_ONE])})
    cache.with_name("last-refresh").write_text("995.0")
    run = Run(cache, rounds=2)
    run.between = lambda: storage.write(cache, {"at": 995.0, "board": board([PR_ONE])})
    run()
    assert run.collected == [], "a refresh the tui has started counts from its start, before the tui saves its board"
    assert run.sleeps == [REFRESH_COOLDOWN + TUI_FIRST - 5, REFRESH_SECONDS - REFRESH_COOLDOWN], \
        "magi web waits for the tui to save its board, then an interval after it, once the tui's next tick has started"


def test_a_refresh_that_died_before_magi_web_started_holds_it_off_only_the_cooldown(cache):
    settings_file(cache)
    cache.with_name("last-refresh").write_text(str(1000.0 - REFRESH_COOLDOWN - TUI_FIRST))
    run = Run(cache, rounds=1)
    run()
    assert run.collected == [1000.0], "a refresh that failed or was stopped with ctrl-c leaves its mark, which waits only the cooldown, as the tui waits"


def test_the_page_is_left_to_the_tui_after_its_own_refreshes(cache):
    settings_file(cache)
    run = Run(cache, rounds=2)

    def tui_refreshes():
        storage.write(cache, {"at": run.now + REFRESH_SECONDS, "board": board([PR_ONE])})
        cache.with_name("last-refresh").write_text(str(run.now + REFRESH_SECONDS))

    run.between = tui_refreshes
    run()
    assert run.collected == [1000.0], "the tui's refresh is not fetched again"
    assert f'data-at="{1000 * 1000}"' in page(cache).read_text(), \
        "the tui writes the page after its own refreshes, so magi web never writes it at the same time"


def test_magi_web_refreshes_with_the_settings_as_they_are_now(cache):
    settings_file(cache)
    teams = []
    run = Run(cache, rounds=4, collect=lambda settings: teams.append(list(settings.team)) or board([PR_ONE]))
    changes = [lambda: settings_file(cache, {**SETTINGS, "team": ["carol"]}), lambda: cache.with_name("config.json").unlink(),
               lambda: cache.with_name("config.json").write_text('{"team": [')]
    run.between = lambda: changes.pop(0)()
    run()
    assert teams[:2] == [["alice", "bob"], ["carol"]], "a team changed with magi config while magi web runs is the one fetched next"
    assert teams[2:] == [["carol"], ["carol"]], "settings removed or half written keep magi web on the ones it had"


def test_a_page_not_written_is_told_and_magi_web_runs_on(cache, monkeypatch):
    settings_file(cache)

    writes = []

    def full_once(*args):
        writes.append(args)
        if len(writes) == 1:
            raise OSError("No space left on device")

    monkeypatch.setattr("magi.tui.web_watch.write_page", full_once)
    run = Run(cache, rounds=2)
    assert run() is None, "a page not written never stops magi web"
    assert "web page not written: No space left on device" in run.said and len(run.collected) == 2, \
        "magi web says why and refreshes again an interval later"
    assert run.opened == [str(page(cache))], "the page opens once it is written, not before"


def test_a_board_not_saved_is_told_and_tried_again(cache, monkeypatch):
    settings_file(cache)

    write_text = storage.write_text

    def full(path, text):
        if path.name == cache.name:
            raise OSError("No space left on device")
        write_text(path, text)

    monkeypatch.setattr("magi.adapters.storage.write_text", full)
    run = Run(cache, rounds=2)
    assert run() is None, "a board not saved never stops magi web"
    assert len(run.collected) == 2 and run.said.count("refresh failed: No space left on device") == 2, \
        "a board fetched but not saved is told, and magi web tries again an interval later"


def test_magi_web_needs_the_settings(cache):
    run = Run(cache, rounds=1)
    assert "run magi config first" in run(), "without settings there is no team to fetch, so magi web says how to set them"
    assert run.collected == [] and not page(cache).exists(), "and it fetches nothing"
    assert run.opened == [], "nor opens anything"
