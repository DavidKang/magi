import asyncio
import os
import subprocess
import sys
import threading
from dataclasses import replace

import pytest
from PIL import Image as PILImage
from textual.content import Content
from textual.widgets import OptionList, Static
from textual_image.widget import Image, get_cell_size

from builders import PR_ONE, PR_THREE, PR_TWO, STATED, board, failing_load, magi_app, make_ticket_detail, settings_file, started
from magi.adapters import storage
from magi.domain.entities import Ticket
from magi.domain.status import column_for
from magi.tui import app as app_module
from magi.tui import entries, screens, theme
from magi.tui.app import MagiApp
from magi.tui.widgets import DetailBody


async def main(cache):
    boards = [board([PR_ONE, PR_TWO]), board([PR_ONE, PR_TWO, PR_THREE])]
    opened, copied, now = [], [], [1000.0]
    app = magi_app(cache, load=lambda: boards.pop(0), opener=opened.append, copier=copied.append, clock=lambda: now[0])
    async with started(app) as pilot:
        detail = lambda: str(app.query_one("#detail", Static).render())
        title = lambda key: str(app.query_one(f"#panel-{key}").border_title)
        focused = lambda key: app.focused is app.query_one(f"#list-{key}")
        assert not app.query("Tabs") and not app.query("#pills") and not app.query(".tab-pill"), "there is no tab bar: one pane holds the boxes"
        assert app.query_one("#panel-details").region.y == app.query_one("#panel-kanban").region.y, "details starts level with the first box"
        assert isinstance(app.query_one("#top #logo"), Image), "the header shows the logo instead of the rocket"
        assert "🚀" not in str(app.query_one("#top .brand").render()), "the header shows the logo instead of the rocket"
        assert app.query_one("#top").outer_size.height == 1, "the header shows the logo instead of the rocket"
        logo, cell = app.query_one("#logo"), get_cell_size()
        width, height = PILImage.open(screens.LOGO).size
        assert str(app.query_one("#top .brand").render()).strip() == "MAGI", "the title reads MAGI"
        assert app.title == "MAGI", "the title reads MAGI"
        assert app.query_one("#panel-kanban").region.y >= app.query_one("#top").region.bottom + 1, "the boxes start one row below the header"
        assert abs(logo.size.width - logo.size.height * cell.height * width / height / cell.width) <= 1, "the logo keeps its proportions"
        status = app.query_one("#status", Static)
        assert str(status.render()).startswith("updated"), "updated time uses the brand color"
        assert status.styles.color == app.query_one(".brand").styles.color, "updated time uses the brand color"
        assert not app.query("#panel-desk"), "there is no my desk or worktrees box"
        assert not app.query("#panel-worktrees"), "there is no my desk or worktrees box"
        titles = [str(panel.border_title) for panel in app.query(".panel")]
        assert titles == ["[1] jira tickets 1", "[2] team prs 2", "[3] changes 1", "details", "[5] factory 0", "[4] epics 1"], \
            "the boxes are numbered from 1, jira tickets, team prs and changes beside the details, and epics sits under the factory"
        assert not app.query("#panel-mine_prs") and not app.query("#panel-mine_tickets"), "the tui has no my prs nor my tickets box"
        assert "Ticket one" in detail(), "the board starts on the jira tickets box"
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
        await pilot.press("2")
        assert focused("prs"), "2 focuses the team prs box"
        assert "Second change" in detail(), "2 focuses the team prs box"
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
        assert app.focused is app.query_one("#top #filter"), "slash focuses the one filter, in the header"
        assert not app.query(".panel Input"), "the boxes have no filter of their own"
        await pilot.press(*"second")
        listed = lambda key: [o.id for o in (app.query_one(f"#list-{key}", OptionList).get_option_at_index(i)
                                             for i in range(app.query_one(f"#list-{key}", OptionList).option_count)) if not o.disabled]
        assert len(listed("prs")) == 1, "the filter narrows every box"
        assert listed("kanban") == [], "the filter narrows every box"
        await pilot.press("enter")
        assert focused("prs") and len(listed("prs")) == 1, "enter goes back to the box, still filtered"
        await pilot.press("escape")
        assert len(listed("prs")) == 2, "escape clears the filter in every box"
        assert len(listed("kanban")) == 1, "escape clears the filter in every box"
        assert focused("prs"), "escape clears the filter"
        await pilot.press("1")
        assert focused("kanban"), "1 focuses the kanban box"
        assert "Ticket one" in detail(), "1 focuses the kanban box"
        await pilot.press("4")
        assert focused("epics"), "4 focuses the epics box"
        assert "Epic one" in detail(), "4 focuses the epics box"
        await pilot.press("3")
        assert focused("changes"), "3 focuses the changes box"
        await pilot.press("4")
        await pilot.press("y")
        assert copied == ["ACME-100"], "y copies the epic key"
        now[0] += 15
        await pilot.press("r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert title("prs") == "[2] team prs 2", "refresh within 30 seconds is skipped"
        assert any("next refresh in 15s" in n.message for n in app._notifications), "skipped refresh says when the next one is allowed"
        now[0] += 16
        await pilot.press("r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert title("prs") == "[2] team prs 3", "refresh reloads the board"
        assert focused("epics"), "refresh keeps the focused box"
        await pilot.press("1")
        await pilot.pause()
        assert focused("kanban") and "Ticket one" in detail(), "1 focuses the kanban box after a refresh"
        assert "app#1" in detail(), "a kanban ticket shows its PRs"
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
        assert str(app.query_one("#panel-prs").border_title) == "[2] team prs 1", "reopening within 30 seconds shows the saved board"
    app = magi_app(cache, load=load, clock=lambda: 1090.0)
    async with started(app):
        assert calls == [1], "reopening after 30 seconds refreshes once"
        assert str(app.query_one("#panel-prs").border_title) == "[2] team prs 3", "refreshed board replaces the saved one"
        assert storage.read(cache)["at"] == 1090.0, "successful refresh saves the board"


def test_reopen(cache):
    asyncio.run(reopen(cache))


async def refresh_keeps_the_row(cache):
    boards = [board([PR_ONE, PR_TWO]), board([PR_THREE, PR_ONE, PR_TWO]), board([PR_THREE, PR_ONE])]
    now = [1000.0]
    app = magi_app(cache, load=lambda: boards.pop(0), clock=lambda: now[0])
    async with started(app) as pilot:
        await pilot.click("#list-prs", offset=(2, 4))
        assert app.current().url == PR_TWO.url, "the click lands on the second pr"
        now[0] += 31
        await pilot.press("r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert str(app.query_one("#panel-prs").border_title) == "[2] team prs 3", "refresh reloads the board"
        assert app.current().url == PR_TWO.url, "refresh keeps the highlighted row when its item is still on the board"
        now[0] += 31
        await pilot.press("r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        prs = app.query_one("#list-prs", OptionList)
        first = next(i for i in range(prs.option_count) if not prs.get_option_at_index(i).disabled)
        assert prs.highlighted == first, "refresh moves to the first row when the highlighted item left the board"


def test_refresh_keeps_the_row(cache):
    asyncio.run(refresh_keeps_the_row(cache))


async def filtering_keeps_the_row(cache):
    boards = [board([PR_ONE, PR_TWO]), board([PR_ONE, PR_TWO, PR_THREE])]
    now = [1000.0]
    app = magi_app(cache, load=lambda: boards.pop(0), clock=lambda: now[0])
    async with started(app) as pilot:
        await pilot.click("#list-prs", offset=(2, 4))
        await pilot.press("slash", *"change")
        assert app.entry(app.query_one("#list-prs", OptionList)).url == PR_TWO.url, "a filter that still shows the row keeps it"
        await pilot.press("escape")
        assert app.current().url == PR_TWO.url, "clearing the filter keeps the row"
        await pilot.press("slash", *"second", "enter")
        now[0] += 31
        await pilot.press("r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        prs = app.query_one("#list-prs", OptionList)
        assert [app.sections["prs"][int(prs.get_option_at_index(i).id)].url for i in range(prs.option_count)
                if not prs.get_option_at_index(i).disabled] == [PR_TWO.url], "a refresh keeps the filter"


def test_filtering_keeps_the_row(cache):
    asyncio.run(filtering_keeps_the_row(cache))


async def filtering_before_the_first_load(cache):
    loaded = threading.Event()
    def load():
        loaded.wait(5)
        return board([PR_ONE])
    app = magi_app(cache, load=load)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.press("slash", "x")
        assert app.query_one("#list-kanban", OptionList).option_count == 0, "a filter typed before the first load leaves the boxes empty"
        loaded.set()


def test_filtering_before_the_first_load(cache):
    asyncio.run(filtering_before_the_first_load(cache))


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


async def overview_heights(cache):
    app = magi_app(cache, load=lambda: board([PR_ONE, PR_TWO]))
    async with started(app, size=(160, 60)):
        shared = [app.query_one(f"#panel-{key}").outer_size.height for key in ("kanban", "prs", "changes")]
    return shared


def test_changes_is_a_bit_shorter_than_kanban_and_team_prs(cache):
    kanban, prs, changes = asyncio.run(overview_heights(cache))
    assert abs(kanban - prs) <= 1, f"kanban and team prs are as tall as each other: {kanban}, {prs}"
    assert changes < min(kanban, prs), f"changes is shorter than kanban and team prs: {kanban}, {prs}, {changes}"
    assert changes * 2 > kanban, f"changes is only a bit shorter, over half kanban's height: {kanban}, {changes}"


def test_digits_reach_the_five_boxes():
    boxes = [binding for binding in MagiApp.BINDINGS if binding.action.startswith("focus_box")]
    assert [(b.key, b.action) for b in boxes] == [(str(n), f"focus_box({n})") for n in range(1, 6)], "digits 1 to 5 reach the boxes, one each"
    assert [(b.key_display, b.description) for b in boxes if b.show] == [("1-5", "boxes")], "the footer shows the digits once, as 1-5"
    assert not any(binding.action.startswith("focus_tab") for binding in MagiApp.BINDINGS), "no key switches tabs: there are none"


async def fitted_description(cache, lines, resized=None):
    ticket = Ticket(key="ACME-1", summary="Ticket one", status="En proceso", assignee="Ana",
                    detail=make_ticket_detail(description="\n".join(f"line {n}" for n in range(1, lines + 1))))
    async with started(magi_app(cache, load=lambda: {**board([]), "kanban": [ticket]}), size=(160, 50)) as pilot:
        await pilot.press("1")
        await pilot.pause()
        if resized:
            await pilot.resize_terminal(*resized)
            await pilot.pause()
        body = pilot.app.query_one("#panel-details .pbody")
        return str(pilot.app.query_one("#detail", Static).render()).splitlines(), body.scrollable_content_region.height


def test_details_fit_a_long_description(cache):
    shown, height = asyncio.run(fitted_description(cache, 80))
    assert len(shown) == height, "a description longer than the details box fills it to its last line"
    assert shown[-1] == "… c to read it all", "a description longer than the details box ends on the hint to read it all"


def test_details_refit_when_the_terminal_resizes(cache):
    shown, height = asyncio.run(fitted_description(cache, 80, resized=(160, 60)))
    assert len(shown) == height and shown[-1] == "… c to read it all", "a resized details box fits the description to its new height"


def test_details_show_a_short_description_whole(cache):
    shown, _ = asyncio.run(fitted_description(cache, 3))
    assert shown[-1] == "line 3" and "… c to read it all" not in shown, "a description that fits the details box shows whole, with no hint"


def snug_ticket(width, height):
    two = Ticket(key="ACME-2", summary="Ticket two", status="En proceso", detail=make_ticket_detail(links=[], comments=[], description="x"))
    # The heading is the detail without its one-row placeholder description; short lines, then one as wide as the box, fill the rest to its last row.
    heading = len(Content.from_markup(entries.ticket_entry(two, [], STATED).detail).wrap(width)) - 1
    description = "\n".join([*(f"line {n}" for n in range(height - heading - 1)), "w" * width])
    return entries.ticket_entry(replace(two, detail=replace(two.detail, description=description)), [], STATED)


async def snug_after_crowded(cache):
    crowded = Ticket(key="ACME-1", summary="Ticket one", status="En proceso", detail=make_ticket_detail(
        links=[{"relation": "relates to", "key": f"ACME-{n}", "summary": "Other", "status": "En proceso"} for n in range(60)]))
    async with started(magi_app(cache, load=lambda: {**board([]), "kanban": [crowded]}), size=(160, 50)) as pilot:
        await pilot.press("1")
        await pilot.pause()
        body = pilot.app.query_one(DetailBody)
        assert body.scrollbar_size_vertical, "a detail taller than the box scrolls"
        snug = snug_ticket(*body.content_region.size)
        body.show(snug.detail, snug.fold)
        await pilot.pause()
        return str(pilot.app.query_one("#detail", Static).render()).splitlines()


def test_details_fit_at_the_box_width_whatever_the_last_detail_scrolled(cache):
    shown = asyncio.run(snug_after_crowded(cache))
    assert shown[-1] == "w" * len(shown[-1]) and "… c to read it all" not in shown, \
        "a description that fits the box at its full width shows whole, even after a detail that showed a scrollbar"


async def ticket_row(cache):
    ticket = Ticket(key="ACME-2", summary="Second ticket", status="En proceso", assignee="Ana")
    async with started(magi_app(cache, load=lambda: {**board([PR_TWO]), "kanban": [ticket]})) as pilot:
        listed = pilot.app.query_one("#list-kanban", OptionList)
        row = next(listed.get_option_at_index(i).prompt.plain for i in range(listed.option_count) if listed.get_option_at_index(i).id)
        return row[:listed.scrollable_content_region.width]


def test_short_labels_leave_room_for_the_summary(cache):
    assert "Second" in asyncio.run(ticket_row(cache)), "the label column takes only the room its longest label needs, so the summary shows"
