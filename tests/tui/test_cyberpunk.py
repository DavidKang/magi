import asyncio
import datetime as dt
import threading
from dataclasses import replace

import pytest
from rich.console import Console
from textual.color import Color
from textual.widgets import Static, Tabs

from builders import EPIC, PR_ONE, SETTINGS, STATED, TICKETS, bare_board, board, make_pr, settings_file
from magi.tui import app as app_module
from magi.tui import entries, theme
from magi.tui.app import MagiApp
from test_nerv import frame_state
from test_theme import pick_theme

# Cyberpunk 2077 has no published palette: its HUD's off-red text, cyan lines and the brand's yellow, picked by eye.
NIGHT_CITY = {"bg": "#000000", "fg": "#ff5c57", "accent": "#fcee0a", "focus": "#fcee0a", "line": "#00f0ff", "blue": "#00f0ff", "bad": "#ff003c",
              "ok": "#1ced7a", "warn": "#ff9a00"}


def start(cache, name, load=lambda: board([PR_ONE])):
    return MagiApp(load=load, opener=print, copier=print, clock=lambda: 1000.0, cache=cache,
                   config_path=settings_file(cache, {**SETTINGS, "theme": name}))


def test_cyberpunk_palette():
    assert {key: theme.THEMES["cyberpunk"][key] for key in NIGHT_CITY} == NIGHT_CITY, "Cyberpunk uses the game's HUD colours"


async def cyberpunk(cache):
    app = start(cache, "cyberpunk")
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.has_class("cyberpunk") and not app.has_class("lcars") and not app.has_class("nerv"), "cyberpunk draws its own frame"
        assert not app.query_one("#sidebar").display and not app.query_one("#elbow").display, "cyberpunk has no LCARS sidebar or elbow"
        assert not app.query_one(Tabs).display and app.query_one("#pills").display, "cyberpunk shows its tabs as blocks"
        bar = app.query_one("#bar")
        assert str(bar.render()).startswith("╱╱╱╱"), "a hatched line tops the screen"
        assert bar.styles.color == Color.parse(NIGHT_CITY["bad"]), "the hatched line turns red on alert"
        assert str(app.query_one("#condition").render()) == "◢ HEAT ★★★★★ ◤", "cyberpunk shows the red alert as a five-star wanted level"
        assert str(app.query_one("#status").render()) == f"NIGHT CITY · NET UPLINK {dt.datetime.fromtimestamp(1000.0):%H:%M}", \
            "cyberpunk times the last refresh by its net uplink"
        titles = {key: str(app.query_one(f"#panel-{key}").border_title) for key in ("attention", "prs", "changes", "epics", "mine_prs", "mine_tickets")}
        assert titles == {"attention": "03-NCPD SCANNER 1", "prs": "04-FIXER GIGS 1", "changes": "05-DATASHARDS 1", "epics": "06-MAIN JOBS 1",
                          "mine_prs": "07-MY GIGS 1", "mine_tickets": "08-SIDE JOBS 2"}, "cyberpunk names the boxes in Night City's words"
        assert str(app.query_one("#panel-details").border_title) == "KIROSHI SCAN", "cyberpunk calls the details a Kiroshi scan"
        pieces = [str(s.render()) for s in app.query_one("#panel-prs .ptitle").query(Static)]
        assert pieces == ["┌─", "◢", "04", "FIXER GIGS", "", "1", "◤", "─┐"], "cyberpunk titles a box with a slanted block on a square line"
        assert app.query_one("#panel-prs .pbody").styles.border_left[0] == "solid", "cyberpunk draws square box lines"
        for key, tone in (("attention", "focus"), ("prs", "line")):
            assert app.query_one(f"#panel-{key} .pbody").styles.border_left[1] == Color.parse(NIGHT_CITY[tone]), \
                f"cyberpunk draws the {key} box {tone == 'focus' and 'yellow, focused' or 'cyan'}"
        assert str(app.query_one("#pill-overview .cap").render()) == "◢", "cyberpunk slants its tabs"
        prompts = [app.query_one("#list-prs").get_option_at_index(i).prompt.plain for i in range(2)]
        assert prompts[0] == "── ON THE AUTHOR (1) ──", "cyberpunk writes the turn groups in capitals"
        assert f"◢ {'RED CI · CONFLICT':<27} ◤" in prompts[1], "cyberpunk slants its badges, keeping their padding"


@pytest.mark.usefixtures("default_theme")
def test_cyberpunk_frame(cache):
    asyncio.run(cyberpunk(cache))


async def cyberpunk_condition(cache, pr):
    app = start(cache, "cyberpunk", lambda: board([pr]))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        return str(app.query_one("#condition").render()), app.query_one("#bar").styles.color


@pytest.mark.usefixtures("default_theme")
@pytest.mark.parametrize("pr, label, tone", [
    (make_pr(review_decision="APPROVED", ci="passing", mergeable="MERGEABLE"), "NO HEAT", "accent"),
    (make_pr(ci="passing", mergeable="MERGEABLE"), "HEAT ★★", "accent"),
    (make_pr(), "HEAT ★★★★★", "bad")])
def test_cyberpunk_condition(cache, pr, label, tone):
    shown, bar = asyncio.run(cyberpunk_condition(cache, pr))
    assert shown == f"◢ {label} ◤", "cyberpunk reads the alert level as Night City's wanted level"
    assert bar == Color.parse(NIGHT_CITY[tone]), "the hatched line is yellow, and red only at five stars"


async def cyberpunk_refreshing(cache):
    release = threading.Event()
    def slow_load():
        release.wait(5)
        return board([PR_ONE])
    async with start(cache, "cyberpunk", slow_load).run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        status = str(pilot.app.query_one("#status").render())
        release.set()
        await pilot.app.workers.wait_for_complete()
    return status


@pytest.mark.usefixtures("default_theme")
def test_cyberpunk_refreshing(cache):
    assert asyncio.run(cyberpunk_refreshing(cache)) == "JACKING IN…", "cyberpunk refreshes by jacking in"


@pytest.mark.usefixtures("default_theme")
def test_cyberpunk_segments_epic_bars():
    theme.use_theme("cyberpunk")
    bar = entries.epic_entry(EPIC, TICKETS, STATED).cells[1][0]
    colours = theme.THEMES["cyberpunk"]
    assert [(bar.plain[s.start:s.end], str(s.style)) for s in bar.spans] == [("█ " * 5, colours["ok"]), ("█ " * 5, colours["raised"])], \
        "cyberpunk splits epic progress into segments, the rest dark"


@pytest.mark.usefixtures("default_theme")
def test_cyberpunk_fills_its_badges():
    theme.use_theme("cyberpunk")
    late = replace(PR_ONE, created_at=f"{dt.date.today() - dt.timedelta(days=58)}T10:00:00Z", review_decision="CHANGES_REQUESTED", ci="passing")
    found = bare_board(prs=[late])
    row = entries.cell_row(entries.entries(found, STATED)["prs"][0], app_module.widths("prs"))
    style = lambda text: row.get_style_at_offset(Console(), row.plain.index(text))
    assert f"◢ {'CHANGES · CONFLICT':<27} ◤    ▲ 58D " in row.plain, "cyberpunk draws what a PR is missing as a slanted badge and a critical age as an alarm"
    assert (style("CHANGES").color.triplet.hex, style("CHANGES").bgcolor.triplet.hex) == (NIGHT_CITY["bg"], NIGHT_CITY["bad"]), \
        "cyberpunk fills its badges in their colour"
    assert (style("▲").color.triplet.hex, style("58D").bold) == (NIGHT_CITY["bad"], True), "cyberpunk flags a critical age in bold red"


async def switched(cache, names):
    async with start(cache, names[0]).run_test(size=(160, 40)) as pilot:
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        states = []
        for name in names[1:]:
            await pick_theme(pilot, name)
            states.append({**frame_state(pilot.app), "cyberpunk": pilot.app.has_class("cyberpunk")})
        return states


async def started_on(cache, name):
    async with start(cache, name).run_test(size=(160, 40)) as pilot:
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        return {**frame_state(pilot.app), "cyberpunk": pilot.app.has_class("cyberpunk")}


@pytest.mark.usefixtures("default_theme")
@pytest.mark.parametrize("names", [("cyberpunk", "okuda", "cyberpunk"), ("nerv", "cyberpunk", "default")])
def test_switching_to_and_from_cyberpunk_leaves_no_frame_behind(cache, names):
    fresh = {name: asyncio.run(started_on(cache, name)) for name in set(names)}
    assert asyncio.run(switched(cache, names)) == [fresh[name] for name in names[1:]], \
        "switching theme draws the new frame as if the app had started in it, with nothing left from the old one"
