import asyncio
import datetime as dt
from dataclasses import replace

import pytest
from rich.console import Console
from textual.color import Color
from textual.widgets import Static, Tabs

from builders import CHANGES, EPIC, PR_ONE, PR_TWO, SETTINGS, STATED, THREAD, TICKETS, board, make_pr, settings_file
from magi.tui import app as app_module
from magi.tui import entries, theme
from magi.tui.app import MagiApp
from test_theme import pick_theme

# nerv-ui's design tokens (github.com/mdrbx/nerv-ui): black, orange text and focus, green grid, red alert, amber warning, cyan data.
MAGI = {"bg": "#000000", "fg": "#ff9900", "accent": "#ff9900", "line": "#00ff00", "focus": "#ff9900", "bad": "#ff0000", "ok": "#00ff00", "warn": "#ffaa00",
        "blue": "#00ffff", "raised": "#1a1a1a"}


def start(cache, name):
    return MagiApp(load=lambda: board([PR_ONE]), opener=print, copier=print, clock=lambda: 1000.0, cache=cache,
                    config_path=settings_file(cache, {**SETTINGS, "theme": name}))


def test_nerv_palettes():
    assert {key: theme.THEMES["nerv"][key] for key in MAGI} == MAGI, "NERV Magi uses the MAGI screens' colours"
    assert "magi" not in theme.THEMES, "NERV Magi is the only NERV theme; the palette on the default layout is gone"


async def nerv(cache):
    app = start(cache, "nerv")
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.has_class("nerv") and not app.has_class("lcars"), "nerv draws its own frame, not LCARS'"
        assert not app.query_one("#sidebar").display, "nerv has no sidebar: the boxes take the full width"
        assert not app.query_one("#elbow").display, "nerv has no LCARS elbow"
        assert not app.query_one(Tabs).display and app.query_one("#pills").display, "nerv shows its tabs as blocks"
        assert app.query_one("#nerv-logo").display and not app.query_one("#top .brand").display, "nerv shows the white logo, not a name"
        assert not app.query_one("#top #logo").display, "nerv shows the white logo, not the coloured one"
        overview, status = app.query_one("#pill-overview").region, app.query_one("#status").content_region
        boxes = [app.query_one(f"#panel-{key}").region for key in ("attention", "details")]
        assert (boxes[0].x, boxes[1].right) == (overview.x, status.right), "nerv lines the boxes up with the overview tab and the status"
        key = app.query_one("FooterKey")
        assert key.region.x == boxes[0].x, "nerv lines its footer up with the boxes"
        assert key.get_component_rich_style("footer-key--description").color.triplet.hex == "#000000", "nerv keeps black footer text on green"
        assert key.get_component_styles("footer-key--description").padding.left == 1, "nerv sets the footer text off its key"
        bar = app.query_one("#bar")
        assert str(bar.render()).startswith("◢◤◢◤"), "a hazard stripe tops the screen"
        assert bar.styles.color == Color.parse(MAGI["bad"]), "the hazard stripe turns red on alert"
        assert str(app.query_one("#condition").render()) == "■ PATTERN BLUE", "nerv flags the red alert as PATTERN BLUE, after nerv-ui's condition line"
        assert str(app.query_one("#status").render()) == f"MAGI · MELCHIOR BALTHASAR CASPER · SYNC {dt.datetime.fromtimestamp(1000.0):%H:%M}", \
            "nerv times the last refresh by the MAGI"
        titles = {key: str(app.query_one(f"#panel-{key}").border_title) for key in ("attention", "prs", "changes", "epics", "mine_prs", "mine_tickets")}
        assert titles == {"attention": "03-EMERGENCY 1", "prs": "04-SORTIES 1", "changes": "05-OPERATIONS LOG 1", "epics": "06-PROJECTS 1",
                          "mine_prs": "07-MY SORTIES 1", "mine_tickets": "08-MY ORDERS 2"}, "nerv names the boxes in NERV's words"
        assert str(app.query_one("#panel-details").border_title) == "MAGI ANALYSIS", "nerv calls the details the MAGI analysis"
        title = app.query_one("#panel-prs .ptitle")
        pieces = [str(s.render()) for s in title.query(Static)]
        assert pieces[:4] + pieces[5:] == ["┏━", "", "■ 04", "SORTIES", "1", "", "━┓"], "nerv writes a box's title into its heavy top line"
        assert pieces[4].startswith("━━━━"), "nerv runs the heavy top line between the title and the count"
        assert title.query_one(".name").styles.color == Color.parse(MAGI["accent"]), "nerv titles are orange text, after nerv-ui's labels"
        assert title.query_one(".code").styles.background == Color.parse(MAGI["bg"]), "nerv titles are text, not filled blocks"
        assert app.query_one("#panel-prs .pbody").styles.border_left[0] == "heavy", "nerv draws heavy box lines"
        for key, tone in (("attention", "focus"), ("prs", "line")):
            box = app.query_one(f"#panel-{key}")
            colours = [box.query_one(".pbody").styles.border_left[1], box.query_one(".ptitle .fill").styles.color,
                       *[edge.styles.color for edge in box.query(".ptitle .edge")]]
            assert colours == [Color.parse(MAGI[tone])] * 4, f"nerv draws the {key} box {tone == 'focus' and 'orange, focused' or 'green'}"
        assert str(app.query_one("#pill-overview .cap").render()) == "▕", "nerv outlines its tabs, after nerv-ui's navigation"
        tabs = [app.query_one(f"#pill-{tab} .seg").styles.color for tab in ("overview", "mine")]
        assert tabs == [Color.parse(MAGI["accent"]), Color.parse(theme.THEMES["nerv"]["dim"])], "nerv lights the current tab orange and dims the rest"
        prompts = [app.query_one("#list-prs").get_option_at_index(i).prompt.plain for i in range(2)]
        assert prompts[0] == "── ON THE AUTHOR (1) ──", "nerv writes the turn groups in capitals"
        assert f"▕ {'RED CI · CONFLICT':<27} ▏" in prompts[1], "nerv outlines its badges, keeping their padding"


@pytest.mark.usefixtures("default_theme")
def test_nerv_frame(cache):
    asyncio.run(nerv(cache))


@pytest.mark.usefixtures("default_theme")
def test_nerv_segments_epic_bars():
    theme.use_theme("nerv")
    bar = entries.epic_entry(EPIC, TICKETS, STATED).cells[1][0]
    nerv = theme.THEMES["nerv"]
    assert [(bar.plain[s.start:s.end], str(s.style)) for s in bar.spans] == [("█ " * 5, nerv["ok"]), ("█ " * 5, nerv["raised"])], \
        "nerv splits epic progress into segments like nerv-ui's sync bars, the rest dark"


async def nerv_review(cache):
    pr_two = replace(PR_TWO, reviews=[*PR_TWO.reviews, CHANGES], threads=[THREAD])
    app = MagiApp(load=lambda: board([PR_ONE, pr_two]), opener=print, copier=print, clock=lambda: 1000.0, cache=cache,
                   config_path=settings_file(cache, {**SETTINGS, "theme": "nerv"}))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.press("4", "j", "c", "j")
        await pilot.pause()
        popup = app.screen.query_one("#review")
        assert popup.styles.border_top == ("heavy", Color.parse(MAGI["accent"])), "the comments popup has nerv's heavy orange line, not a filled bar"
        assert popup.styles.border_title_color == Color.parse(MAGI["accent"]), "the comments popup titles itself in orange text"
        assert app.screen.query_one("#review-diff-box").styles.border_top[0] == "heavy", "nerv draws the diff box with a heavy line"


@pytest.mark.usefixtures("default_theme")
def test_nerv_review_popup(cache):
    asyncio.run(nerv_review(cache))


async def nerv_condition(cache, pr):
    app = MagiApp(load=lambda: board([pr]), opener=print, copier=print, clock=lambda: 1000.0, cache=cache,
                   config_path=settings_file(cache, {**SETTINGS, "theme": "nerv"}))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        shown = app.query_one("#condition").render()
        return shown.plain, [(span.style.foreground, span.style.bold) for span in shown.spans], app.query_one("#bar").styles.color


@pytest.mark.usefixtures("default_theme")
@pytest.mark.parametrize("pr, label, tone", [
    (make_pr(review_decision="APPROVED", ci="passing", mergeable="MERGEABLE"), "NORMAL", "ok"),
    (make_pr(ci="passing", mergeable="MERGEABLE"), "PATTERN ORANGE", "warn"),
    (make_pr(), "PATTERN BLUE", "bad")])
def test_nerv_condition(cache, pr, label, tone):
    shown, styles, bar = asyncio.run(nerv_condition(cache, pr))
    assert (shown, styles) == (f"■ {label}", [(Color.parse(MAGI[tone]), None), (Color.parse(MAGI[tone]), True)]), "nerv marks the alert level in its own colour"
    assert bar == Color.parse(MAGI["bad" if tone == "bad" else "accent"]), "the hazard stripe is orange, and red only on PATTERN BLUE"


def frame_state(app):
    pieces = [str(s.render()) for s in app.query_one("#panel-prs .ptitle").query(Static)]
    return {"classes": {name for name in ("framed", "lcars", "nerv", "eva01") if app.has_class(name)},
            "brand": [app.query_one(sel).display for sel in ("#top .brand", "#top #logo", "#nerv-logo")], "bar": str(app.query_one("#bar").render())[:4],
            "condition": str(app.query_one("#condition").render()), "status": str(app.query_one("#status").render()),
            "title": str(app.query_one("#panel-prs").border_title), "pieces": pieces[:4] + pieces[5:], "fill": pieces[4][:4],
            "tab": str(app.query_one("#pill-overview .cap").render())}


async def started_on(cache, name):
    async with start(cache, name).run_test(size=(160, 40)) as pilot:
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        return frame_state(pilot.app)


async def switched(cache, names):
    async with start(cache, names[0]).run_test(size=(160, 40)) as pilot:
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        states = []
        for name in names[1:]:
            await pick_theme(pilot, name)
            states.append(frame_state(pilot.app))
        return states


@pytest.mark.usefixtures("default_theme")
@pytest.mark.parametrize("names", [("nerv", "okuda", "default"), ("okuda", "nerv", "okuda"), ("nerv", "eva01", "nerv")])
def test_switching_themes_leaves_no_frame_behind(cache, names):
    fresh = {name: asyncio.run(started_on(cache, name)) for name in set(names)}
    assert asyncio.run(switched(cache, names)) == [fresh[name] for name in names[1:]], \
        "switching theme draws the new frame as if the app had started in it, with nothing left from the old one"


@pytest.mark.usefixtures("default_theme")
def test_nerv_outlines_its_badges():
    theme.use_theme("nerv")
    late = replace(PR_ONE, created_at=f"{dt.date.today() - dt.timedelta(days=58)}T10:00:00Z", review_decision="CHANGES_REQUESTED",
                   ci="passing")
    found = {"prs": [late], "review_prs": [], "by_key": {}, "attention": [], "changes": [], "epics": [], "my_prs": [], "my_tickets": []}
    row = entries.cell_row(entries.entries(found, STATED)["prs"][0], app_module.widths("prs"))
    style = lambda text: row.get_style_at_offset(Console(), row.plain.index(text))
    assert f"▕ {'CHANGES · CONFLICT':<27} ▏    ▲ 58D " in row.plain, \
        "nerv draws what a PR is missing as an outlined badge and a critical age as an alarm, after nerv-ui"
    for text in ("▕ CHANGES", "CHANGES", "CONFLICT"):
        assert (style(text).color.triplet.hex, style(text).bgcolor) == (MAGI["bad"], None), "nerv badges are coloured text in a thin outline, not filled"
    assert (style("▲").color.triplet.hex, style("58D").bold) == (MAGI["bad"], True), "nerv flags a critical age in bold red"
    calm = replace(PR_ONE, created_at=f"{dt.date.today() - dt.timedelta(days=2)}T10:00:00Z", review_decision="APPROVED", ci="passing",
                   mergeable="MERGEABLE")
    row = entries.cell_row(entries.entries({**found, "prs": [calm]}, STATED)["prs"][0], app_module.widths("prs"))
    assert f"▕ {'APPROVED':<27} ▏ {'2d':>8} " in row.plain, "nerv leaves a nominal age plain"
    assert (style("APPROVED").color.triplet.hex, style("2d").color.triplet.hex) == (MAGI["ok"], theme.THEMES["nerv"]["dim"]), \
        "nerv outlines a PR ready to merge in green and dims a nominal age"
