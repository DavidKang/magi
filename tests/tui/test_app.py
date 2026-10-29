import asyncio
import os
import subprocess
import sys
import threading

import pytest
from PIL import Image as PILImage
from textual.widgets import OptionList, Static
from textual_image.widget import Image, get_cell_size

from builders import PR_ONE, PR_THREE, PR_TWO, STATED, board, failing_load, magi_app, settings_file, started
from magi.adapters import storage
from magi.domain.status import column_for
from magi.tui import app as app_module
from magi.tui import screens, theme
from magi.tui.app import MagiApp


async def main(cache):
    boards = [board([PR_ONE, PR_TWO]), board([PR_ONE, PR_TWO, PR_THREE])]
    opened, copied, now = [], [], [1000.0]
    app = magi_app(cache, load=lambda: boards.pop(0), opener=opened.append, copier=copied.append, clock=lambda: now[0])
    async with started(app) as pilot:
        detail = lambda: str(app.query_one("#detail", Static).render())
        title = lambda key: str(app.query_one(f"#panel-{key}").border_title)
        focused = lambda key: app.focused is app.query_one(f"#list-{key}")
        assert [tab.label.plain for tab in app.query("Tab")] == ["[1] Overview", "[2] Mine", "[9] Factory"], \
            "the tab bar shows Overview, Mine and the factory, Overview first"
        assert app.query_one("Tabs").active == "tab-overview", "the tab bar shows Overview and Mine, Overview first"
        assert app.query_one("Tabs").region.width == app.screen.region.width, "the tab bar spans the whole width"
        assert app.query_one("#panel-details").region.y == app.query_one("#panel-attention").region.y, "details starts level with the first box"
        assert isinstance(app.query_one("#top #logo"), Image), "the header shows the logo instead of the rocket"
        assert "🚀" not in str(app.query_one("#top .brand").render()), "the header shows the logo instead of the rocket"
        assert app.query_one("#top").outer_size.height == 1, "the header shows the logo instead of the rocket"
        logo, cell = app.query_one("#logo"), get_cell_size()
        width, height = PILImage.open(screens.LOGO).size
        assert str(app.query_one("#top .brand").render()).strip() == "MAGI", "the title reads MAGI"
        assert app.title == "MAGI", "the title reads MAGI"
        assert app.query_one("#panel-attention").region.y >= app.query_one("#top").region.bottom + 1, "the boxes start one row below the header"
        assert abs(logo.size.width - logo.size.height * cell.height * width / height / cell.width) <= 1, "the logo keeps its proportions"
        status = app.query_one("#status", Static)
        assert str(status.render()).startswith("updated"), "updated time uses the brand color"
        assert status.styles.color == app.query_one(".brand").styles.color, "updated time uses the brand color"
        assert not app.query("#panel-desk"), "there is no my desk or worktrees box"
        assert not app.query("#panel-worktrees"), "there is no my desk or worktrees box"
        titles = [str(panel.border_title) for panel in app.query(".panel")]
        assert titles == ["[3] attention 1", "[4] team prs 2", "[5] changes 1", "[6] epics 1", "[7] my prs 1", "[8] my tickets 2", "[9] factory 0", "details"], \
            "overview numbers its boxes next to details"
        assert "Move it to In review?" in detail(), "overview starts on the attention box"
        heights = {key: app.query_one(f"#panel-{key}").outer_size.height for key in ("attention", "prs", "changes", "epics")}
        assert heights["attention"] == 5, "attention box fits its items"
        assert heights["epics"] == 5, "epics box fits its items"
        assert abs(heights["prs"] - heights["changes"]) <= 1, "team prs and changes share the rest"
        assert heights["prs"] > 5, "team prs and changes share the rest"
        prompts = [app.query_one("#list-prs", OptionList).get_option_at_index(i).prompt for i in range(5)]
        assert [p.plain for p in prompts[2:4]] == ["", "── ready to merge (1) ──"], "a blank line separates the groups"
        assert str(prompts[0].style) == f"bold {theme.THEMES['default']['fg']}", "group headers stand out in bold, in the text colour"
        await pilot.click("#list-prs", offset=(2, 4))
        assert "Second change" in detail(), "click in the team prs box shows that PR"
        await pilot.click("#list-changes", offset=(2, 0))
        assert "New PR" in detail(), "click in the changes box shows that change"
        await pilot.press("enter")
        assert opened == [PR_ONE.url], "enter opens the item of the focused box"
        opened.clear()
        await pilot.press("4")
        assert focused("prs"), "4 focuses the team prs box"
        assert "Second change" in detail(), "4 focuses the team prs box"
        await pilot.press("k")
        assert "[ACME-1] First change" in detail(), "k moves up, detail keeps the ticket prefix"
        await pilot.press("j")
        assert "Second change" in detail(), "j moves to next PR"
        assert str(app.query_one("#list-prs", OptionList).get_option_at_index(4).prompt).rstrip().endswith(" brs"), "long repo shown as alias"
        await pilot.press("enter")
        assert opened == [PR_TWO.url], "enter opens the PR"
        await pilot.click("#list-prs", offset=(2, 1))
        assert "First change" in detail(), "click on a row selects it"
        await pilot.click("#detail", offset=(10, 2))
        assert opened[-1] == PR_ONE.url, "click on a detail link opens it"
        await pilot.press("slash")
        assert app.focused is app.query_one("#filter-prs"), "slash focuses the filter of the focused box"
        await pilot.press(*"second")
        listed = lambda: [o.id for o in (app.query_one("#list-prs", OptionList).get_option_at_index(i)
                                          for i in range(app.query_one("#list-prs", OptionList).option_count)) if not o.disabled]
        assert len(listed()) == 1, "filter narrows the list"
        await pilot.press("escape")
        assert len(listed()) == 2, "escape clears the filter"
        assert focused("prs"), "escape clears the filter"
        await pilot.press("3")
        assert focused("attention"), "3 focuses the attention box"
        assert "Move it to In review?" in detail(), "3 focuses the attention box"
        await pilot.press("6")
        assert focused("epics"), "6 focuses the epics box"
        assert "Epic one" in detail(), "6 focuses the epics box"
        await pilot.press("5")
        assert focused("changes"), "5 focuses the changes box"
        await pilot.press("6")
        await pilot.press("y")
        assert copied == ["ACME-100"], "y copies the epic key"
        now[0] += 15
        await pilot.press("r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert title("prs") == "[4] team prs 2", "refresh within 30 seconds is skipped"
        assert any("next refresh in 15s" in n.message for n in app._notifications), "skipped refresh says when the next one is allowed"
        now[0] += 16
        await pilot.press("r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert title("prs") == "[4] team prs 3", "refresh reloads the board"
        assert focused("epics"), "refresh keeps the focused box"
        tabs = app.query_one("Tabs")
        await pilot.press("7")
        await pilot.pause()
        assert tabs.active == "tab-mine", "7 opens the mine tab on my open prs"
        assert focused("mine_prs"), "7 opens the mine tab on my open prs"
        assert "First change" in detail(), "7 opens the mine tab on my open prs"
        await pilot.press("8")
        await pilot.pause()
        tickets = app.query_one("#list-mine_tickets", OptionList)
        prompts = [str(tickets.get_option_at_index(i).prompt) for i in range(tickets.option_count)]
        assert len(prompts) == 5, "my tickets are grouped under their status, a blank line between groups"
        assert prompts[0].startswith("── Todo (1)"), "my tickets are grouped under their status"
        assert "OPS-7" in prompts[1], "my tickets are grouped under their status"
        assert prompts[2] == "", "my tickets are grouped under their status, a blank line between groups"
        assert prompts[3].startswith("── In Progress (1)"), "my tickets are grouped under their status"
        assert "ACME-1" in prompts[4], "my tickets are grouped under their status"
        assert focused("mine_tickets"), "8 focuses my tickets on the first ticket"
        assert "Ticket seven" in detail(), "8 focuses my tickets on the first ticket"
        assert "creator" not in detail(), "a ticket cached before the detail fetch shows no detail fields"
        assert "epic" not in detail(), "a ticket cached before the detail fetch shows no detail fields"
        await pilot.press("c")
        await pilot.pause()
        assert not isinstance(app.screen, app_module.ReviewScreen), "c on a ticket cached before the detail fetch opens nothing"
        assert any("no review comments" in n.message for n in app._notifications), \
            "c on a ticket cached before the detail fetch says it has no review comments"
        await pilot.press("slash", *"seven")
        await pilot.pause()
        prompts = [str(tickets.get_option_at_index(i).prompt) for i in range(tickets.option_count)]
        assert len(prompts) == 2, "filtering my tickets drops the groups with no match"
        assert prompts[0].startswith("── Todo (1)"), "filtering my tickets drops the groups with no match"
        assert "OPS-7" in prompts[1], "filtering my tickets drops the groups with no match"
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()
        assert tabs.active == "tab-mine", "2 on the mine tab keeps the focused box"
        assert focused("mine_tickets"), "2 on the mine tab keeps the focused box"
        assert "Ticket seven" in detail(), "2 on the mine tab keeps the focused box"
        await pilot.press("j")
        assert "Ticket one" in detail(), "j skips the status line to the next ticket, with its PRs"
        assert "app#1" in detail(), "j skips the status line to the next ticket, with its PRs"
        await pilot.press("enter")
        assert opened[-1] == "https://acme.atlassian.net/browse/ACME-1", "enter opens the ticket in Jira"
        await pilot.press("c")
        await pilot.pause()
        popup = app.screen
        listing = popup.query_one(OptionList)
        prompts = [str(listing.get_option_at_index(i).prompt) for i in range(listing.option_count)]
        assert isinstance(popup, app_module.ReviewScreen), "c opens the ticket's description and comments"
        assert len(prompts) == 2, "c opens the ticket's description and comments"
        assert prompts[0].splitlines()[:2] == ["description", "Bob"], "c opens the ticket's description and comments"
        assert prompts[1].splitlines() == ["comment", "Carol", "Looks good"], "c opens the ticket's description and comments"
        assert "ACME-1 · Ticket one" in str(popup.query_one("#review").border_title), "the ticket popup is titled with the key and summary"
        assert "Use the new reason column." in str(popup.query_one("#review-comments", Static).render()), \
            "the ticket popup shows the whole description"
        await pilot.press("j", "enter")
        assert opened[-1] == "https://acme.atlassian.net/browse/ACME-1?focusedCommentId=10", "enter on a ticket comment opens that comment in Jira"
        await pilot.press("escape")
        await pilot.press("1")
        await pilot.pause()
        assert tabs.active == "tab-overview", "1 goes back to the overview tab"
        assert focused("attention"), "1 goes back to the overview tab"
        await pilot.press("2")
        await pilot.pause()
        assert tabs.active == "tab-mine", "2 opens the mine tab"
        assert focused("mine_prs"), "2 opens the mine tab"
        await pilot.press("1")
        await pilot.pause()
        await pilot.click("#tab-mine")
        await pilot.pause()
        assert tabs.active == "tab-mine", "clicking the mine tab focuses my prs"
        assert focused("mine_prs"), "clicking the mine tab focuses my prs"


@pytest.mark.usefixtures("aliases")
def test_main(cache):
    asyncio.run(main(cache))


def unmapped_load():
    column_for("Blocked")


async def unmapped_status(cache):
    app = magi_app(cache, load=unmapped_load)
    async with app.run_test(size=(160, 40)) as pilot:
        try:
            await asyncio.wait_for(app.workers.wait_for_complete(), 5)
        except TimeoutError:
            pass
        await pilot.pause()
        assert not app.refreshing, "an unmapped jira status fails the refresh instead of leaving it running"
        assert any("Unmapped Jira status: Blocked" in n.message for n in app._notifications), \
            "an unmapped jira status fails the refresh instead of leaving it running"


def test_unmapped_status(cache):
    asyncio.run(unmapped_status(cache))


async def reopen(cache):
    calls = []
    def load():
        calls.append(1)
        return board([PR_ONE, PR_TWO, PR_THREE])
    storage.write(cache, {"at": 1000.0, "board": board([PR_ONE])})
    app = magi_app(cache, load=load, clock=lambda: 1015.0)
    async with started(app):
        assert calls == [], "reopening within 30 seconds does not refresh"
        assert str(app.query_one("#panel-prs").border_title) == "[4] team prs 1", "reopening within 30 seconds shows the saved board"
    app = magi_app(cache, load=load, clock=lambda: 1090.0)
    async with started(app):
        assert calls == [1], "reopening after 30 seconds refreshes once"
        assert str(app.query_one("#panel-prs").border_title) == "[4] team prs 3", "refreshed board replaces the saved one"
        assert storage.read(cache)["at"] == 1090.0, "successful refresh saves the board"


def test_reopen(cache):
    asyncio.run(reopen(cache))


async def throttle_across_runs(cache):
    calls = []
    def load():
        calls.append(1)
        return board([PR_ONE])
    async with started(magi_app(cache, load=failing_load)):
        pass
    app = magi_app(cache, load=load, clock=lambda: 1015.0)
    async with started(app) as pilot:
        assert calls == [], "reopening within 30 seconds of a failed refresh does not refresh"
        assert "next refresh in 15s" in str(app.query_one("#status", Static).render()), "an empty board says when it will refresh"
        await pilot.press("r")
        await pilot.pause()
        assert calls == [], "r within 30 seconds of a refresh in an earlier run is skipped"
        assert any("next refresh in 15s" in n.message for n in app._notifications), "r within 30 seconds of a refresh in an earlier run is skipped"
    async with started(magi_app(cache, load=load, clock=lambda: 1031.0)):
        assert calls == [1], "reopening after 30 seconds refreshes"


def test_throttle_across_runs(cache):
    asyncio.run(throttle_across_runs(cache))


async def running(cache):
    release, calls = threading.Event(), []
    def slow_load():
        calls.append(1)
        release.wait(5)
        return board([PR_ONE])
    now = [1000.0]
    app = magi_app(cache, load=slow_load, clock=lambda: now[0])
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        now[0] += 120
        await pilot.press("r")
        await pilot.pause()
        assert any("refresh already running" in n.message for n in app._notifications), "refresh while one is running is skipped"
        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(calls) == 1, "only one load ran"


def test_running(cache):
    asyncio.run(running(cache))


async def failure(cache):
    app = magi_app(cache, load=failing_load)
    async with started(app):
        assert app.is_running, "failed refresh keeps the app running"
        assert any("API rate limit exceeded" in n.message for n in app._notifications), "failed refresh shows the command error"
        assert not cache.exists(), "failed refresh saves nothing"


def test_failure(cache):
    asyncio.run(failure(cache))


def test_quit_while_refreshing(cache):
    started, release, finished, loads = threading.Event(), threading.Event(), threading.Event(), []

    def load():
        loads.append(threading.current_thread())
        started.set()
        release.wait(10)
        finished.set()
        return board([PR_ONE])

    async def run():
        app = magi_app(cache, load=load)
        async with app.run_test(size=(160, 40)) as pilot:
            await asyncio.to_thread(started.wait, 5)
            await pilot.press("q")
    asyncio.run(run())
    assert started.is_set(), "quitting does not wait for a running refresh"
    assert not finished.is_set(), "quitting does not wait for a running refresh"
    errors, hook = [], threading.excepthook
    threading.excepthook = errors.append
    try:
        release.set()
        for thread in loads:
            thread.join(5)
    finally:
        threading.excepthook = hook
    assert finished.is_set(), "a refresh that ends after quitting finishes quietly"
    assert errors == [], "a refresh that ends after quitting finishes quietly"


QUIT_SCRIPT = """
import asyncio, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from magi.adapters import process
from magi.tui import app as app_module

cache, done, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
started = threading.Event()


def item(_):
    started.set()
    time.sleep(0.5)
    with done.open("a") as out:
        out.write("x")


def load():
    if mode == "running":
        return process.parallel(item, range(40))
    if mode == "failed":
        pool = ThreadPoolExecutor(max_workers=8)
        for n in range(40):
            pool.submit(item, n)
        started.wait(5)
    raise RuntimeError("gh failed")


async def run():
    app = app_module.MagiApp(load=load, opener=print, copier=print, cache=cache, config_path=cache.with_name("config.json"))
    async with app.run_test(size=(160, 40)) as pilot:
        if mode == "running":
            await asyncio.to_thread(started.wait, 5)
        else:
            await app.workers.wait_for_complete()
        await pilot.pause()
        if mode == "code":
            app.exit(return_code=3)
        else:
            await pilot.press("q")
    return app


app_module.leave(asyncio.run(run()))
"""


def quit_script(cache, mode):
    cache = cache.parent / mode / cache.name
    cache.parent.mkdir()
    settings_file(cache)
    done = cache.with_name("done")
    try:
        result = subprocess.run([sys.executable, "-c", QUIT_SCRIPT, str(cache), str(done), mode], capture_output=True, text=True, timeout=60,
                                env={**os.environ, "HOME": str(cache.parent)})
    except subprocess.TimeoutExpired:
        return None, 40
    return result.returncode, len(done.read_text()) if done.exists() else 0


def test_quit_drops_queued_fetches(cache):
    code, finished = quit_script(cache, "running")
    assert code == 0, "quitting mid-refresh drops the fetches still queued"
    assert finished < 40, "quitting mid-refresh drops the fetches still queued"
    code, finished = quit_script(cache, "failed")
    assert code == 0, "quitting after a failed refresh drops the fetches it left queued"
    assert finished < 40, "quitting after a failed refresh drops the fetches it left queued"
    code, _ = quit_script(cache, "code")
    assert code == 3, "the app's exit code reaches the shell"


def test_tui_loads_the_board():
    asked = []
    app = MagiApp(collect=lambda settings: asked.append(settings) or "board")
    app.settings = STATED
    assert app.load() == "board", "the TUI refresh collects the board with the app's settings"
    assert asked == [STATED], "the TUI refresh collects the board with the app's settings"


def test_refresh_policy():
    assert app_module.REFRESH_SECONDS == 5 * 60, "the board refreshes itself every 5 minutes"
