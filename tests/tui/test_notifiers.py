import asyncio
import subprocess
import threading

import pytest

from builders import PR_ONE, PR_TWO, board, magi_app, started
from magi.adapters import storage
from magi.tui import app as app_module
from magi.tui import notifiers


class Told:
    """A notifier that keeps what the app told it, and whether the news reached it outside the app's thread."""

    def __init__(self):
        self.calls = []
        self.apart = []

    def news(self):
        self.calls.append("news")
        self.apart.append(threading.current_thread() is not threading.main_thread())

    def leave(self):
        self.calls.append("leave")


def test_magi_tells_the_multiplexer_it_runs_in():
    herdr = notifiers.notifier({"HERDR_PANE_ID": "p7", "TERM": "xterm"})
    assert (type(herdr), herdr.pane) == (notifiers.Herdr, "p7"), "in a herdr pane magi tells herdr, about that pane"
    assert type(notifiers.notifier({"TERM": "xterm"})) is notifiers.Silent, "outside any multiplexer magi tells nobody"
    assert type(notifiers.notifier({"HERDR_PANE_ID": ""})) is notifiers.Silent, "an empty pane id is no herdr pane"


def test_herdr_marks_the_workspace_as_an_agent_that_finished(monkeypatch):
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **options: ran.append((cmd, options)))
    herdr = notifiers.Herdr("p7")
    herdr.news()
    herdr.leave()
    agent = ["--source", "magi", "--agent", "magi"]
    assert [cmd for cmd, _ in ran] == [["herdr", "pane", "report-agent", *agent, "--state", "working", "p7"],
                                       ["herdr", "pane", "report-agent", *agent, "--state", "idle", "p7"],
                                       ["herdr", "pane", "release-agent", *agent, "p7"]], \
        "news is a turn that ended, which herdr marks on the workspace with its done sound; leaving gives the pane back"
    assert all(options.get("check") is False and options.get("capture_output") and options.get("timeout") for _, options in ran), \
        "a herdr that fails or hangs never breaks the board nor writes over it"


@pytest.mark.parametrize("error", [FileNotFoundError("herdr"), subprocess.TimeoutExpired("herdr", 1)])
def test_a_herdr_missing_or_hung_is_no_reason_to_stop(monkeypatch, error):
    tried = []

    def fail(cmd, **options):
        tried.append(cmd[2])
        raise error
    monkeypatch.setattr(subprocess, "run", fail)
    herdr = notifiers.Herdr("p7")
    herdr.news()
    herdr.news()
    herdr.leave()
    assert tried == ["report-agent", "report-agent", "release-agent"], \
        "a herdr missing or stuck never stops magi: each telling ends at its first failure, and the next one tries again"


def test_herdr_leaves_after_the_news_it_is_telling(monkeypatch):
    ran, reporting, telling = [], threading.Event(), threading.Event()

    def run(cmd, **options):
        ran.append(cmd[cmd.index("--state") + 1] if "--state" in cmd else cmd[2])
        if ran[-1] == "working":
            reporting.set()
            telling.wait(5)
    monkeypatch.setattr(subprocess, "run", run)
    herdr = notifiers.Herdr("p7")
    news = threading.Thread(target=herdr.news)
    news.start()
    reporting.wait(5)
    leaving = threading.Thread(target=herdr.leave)
    leaving.start()
    leaving.join(0.2)
    telling.set()
    news.join(5)
    leaving.join(5)
    herdr.news()
    assert ran == ["working", "idle", "release-agent"], \
        "quitting waits for the news being told, so herdr gets the pane back last; news after leaving tells nothing"


def test_magi_tells_the_multiplexer_named_by_its_environment(monkeypatch):
    made = {}

    class Board:
        def __init__(self, *args, **options):
            made.update(options)

        def run(self):
            pass
    monkeypatch.setattr(app_module, "MagiApp", Board)
    monkeypatch.setattr(app_module, "leave", lambda app: None)
    monkeypatch.setenv("HERDR_PANE_ID", "p9")
    app_module.main(lambda settings: None, lambda key: None)
    assert (type(made["notifier"]), made["notifier"].pane) == (notifiers.Herdr, "p9"), "magi tells the multiplexer its environment names"


def with_news(at):
    found = board([PR_ONE, PR_TWO])
    found["changes"] = [{**found["changes"][0], "at": at}]
    return found


async def refreshes(cache):
    storage.write(cache.with_name("seen.json"), {"seen": {PR_ONE.url: "2026-10-24T02:04 New PR"}})
    told = Told()
    loaded = {"board": with_news("2026-10-24T02:04")}
    app = magi_app(cache, load=lambda: loaded["board"], notifier=told)
    async with started(app) as pilot:
        assert told.calls == [], "a board with nothing unseen tells nothing"
        loaded["board"] = with_news("2026-10-25T03:00")
        app.start_refresh()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert told.calls == ["news"], "a refresh that brings an unseen change tells the multiplexer"
        assert told.apart == [True], "the multiplexer is told off the app's thread, so a slow one never holds the board"
        app.start_refresh()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert told.calls == ["news"], "a refresh that brings nothing new tells nothing, though the last change is still unseen"
    assert told.calls == ["news", "leave"], "quitting gives the pane back"


@pytest.mark.usefixtures("default_theme")
def test_a_refresh_with_news_tells_the_multiplexer(cache):
    asyncio.run(refreshes(cache))


async def first_board(cache):
    storage.write(cache.with_name("seen.json"), {"seen": {PR_ONE.url: "2026-10-23T01:00 Old change"}})
    told = Told()
    app = magi_app(cache, load=lambda: with_news("2026-10-24T02:04"), notifier=told)
    async with started(app):
        assert told.calls == [], "the first board of a session tells nothing, though it has unseen changes: magi tells what arrives while it runs"


@pytest.mark.usefixtures("default_theme")
def test_the_first_board_tells_nothing(cache):
    asyncio.run(first_board(cache))


async def first_refresh_over_a_cache(cache):
    storage.write(cache, {"at": 1000.0, "board": with_news("2026-10-24T02:04")})
    storage.write(cache.with_name("seen.json"), {"seen": {PR_ONE.url: "2026-10-24T02:04 New PR"}})
    told = Told()
    loads = []
    app = magi_app(cache, load=lambda: loads.append(1) or with_news("2026-10-25T03:00"), notifier=told, clock=lambda: 2000.0)
    async with started(app):
        assert loads == [1], "a saved board past the cooldown is refreshed on start"
        assert told.calls == [], "the refresh that starts a session tells nothing, though it brings news past the saved board"


@pytest.mark.usefixtures("default_theme")
def test_the_first_refresh_over_a_saved_board_tells_nothing(cache):
    asyncio.run(first_refresh_over_a_cache(cache))
