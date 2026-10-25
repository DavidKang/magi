import asyncio
import datetime as dt
import json
import threading

import pytest
from textual.color import Color
from textual.widgets import Footer, Input, OptionList, Static, Tabs
from textual.widgets._footer import FooterKey
from textual_image.widget import get_cell_size

from builders import ALERT_PRS, PR_ONE, PR_TWO, SETTINGS, TICKETS, board, failing_load, magi_app, make_epic, pick_theme, started
from magi import rows
from magi.tui import screens, theme
from magi.tui.screens import ThemeScreen


async def lcars_theme(cache):
    lcars = theme.THEMES["okuda"]
    app = magi_app(cache)
    path = app.config_path
    async with started(app) as pilot:
        assert app.screen.styles.background == Color.parse(theme.THEMES["default"]["bg"]), "a config without a theme starts with the default one"
        assert not any(app.query_one(f"#{name}").display for name in ("elbow", "bar", "sidebar", "condition", "pills")), "the default theme has no LCARS frame"
        assert app.query_one(Tabs).display, "the default theme keeps its tabs"
        assert app.query_one("#top #logo").display and not app.query_one("#elbow-logo").display, "the default theme keeps its logo in the masthead"
        assert app.query_one("#top").region.y == 1, "the default theme leaves a row above its header"
        assert not any(app.query_one(f"#{name}").display for name in ("footcap", "foot-cap")) and app.query_one(Footer).region.x == 0, \
            "the default theme keeps its footer"
        assert not any(title.display for title in app.query(".ptitle")), "the default theme keeps its bordered titles"
        await pick_theme(pilot, "okuda")
        assert app.query_one("#elbow").display, "LCARS frames the header with an elbow"
        assert app.query_one("#bar").display, "LCARS frames the header with an elbow"
        assert str(app.query_one("#top .brand").render()) == "MAGI", "LCARS frames the header with an elbow"
        assert str(app.query_one("#elbow").render()).splitlines() == ["▗▄" + " " * 11, " " * 12 + "▘", " " * 13, " " * 13, "  04-1701    "], \
            "LCARS rounds the elbow's outer corner, fillets the inner one and carries a panel code"
        assert str(app.query_one("#bar").render()) == "\ue0b4", "the LCARS bar ends in a round cap"
        mark, corner = app.query_one("#elbow-logo"), app.query_one("#elbow").region
        assert (mark.region.y, mark.region.height) == (corner.y + 1, 2), "LCARS sets its logo inside the elbow"
        assert abs((mark.region.x - corner.x) - (corner.right - 1 - mark.region.right)) <= 1, "LCARS centres its logo in the elbow"
        assert mark.image.tobytes() == screens.logo_image(2, get_cell_size(), screens.LOGO_BLACK)[0].tobytes(), "LCARS uses the black logo"
        assert not app.query_one("#top #logo").display, "LCARS moves the logo out of the masthead"
        assert app.query_one("#bar").region.right == app.screen.region.right, "the logo in the elbow leaves the bar its full width"
        assert app.query_one("#sidebar").region.y == app.query_one("#elbow").region.bottom + 1, "the LCARS elbow sits one row above the sidebar, like its buttons"
        assert not app.query_one(Tabs).display, "LCARS swaps the tabs for pills"
        pills = list(app.query(".tab-pill"))
        assert ["".join(str(s.render()) for s in pill.query(Static)) for pill in pills] == ["\ue0b6 01 OVERVIEW \ue0b4", "\ue0b6 02 MINE \ue0b4"], \
            "LCARS swaps the tabs for pills"
        assert [pill.has_class("-on") for pill in pills] == [True, False], "the pill of the shown tab is lit"
        title = app.query_one("#panel-prs .ptitle")
        assert title.display, "LCARS titles panels with a pill"
        assert [str(s.render()) for s in title.query(Static)] == ["╭─", "\ue0b6", "04", "CREW REPORTS", "", "1", "\ue0b4", "─╮"], \
            "LCARS titles panels with a pill set into the box's top line: code, name, filler and count"
        assert [str(s.render()) for s in app.query_one("#panel-details").query(".ptitle Static")][3] == "SENSOR READINGS", "the details panel has a pill title too"
        assert app.query_one("#top").region.y == app.query_one("#bar").region.y + 2, "the LCARS masthead leaves a row under the bar"
        assert app.query_one("#pills").region.y == app.query_one("#top").region.y + 2, "the LCARS pills leave a row around them"
        assert app.query_one("#sidebar").region.y == app.query_one("#pills").region.y + 2, "the LCARS pills leave a row around them"
        assert app.query_one("#panel-epics").region.bottom == app.query_one("#panel-details").region.bottom, "the LCARS columns end on the same row"
        foot_cap = app.query_one("#foot-cap")
        assert (str(foot_cap.render()), foot_cap.region.x) == ("\ue0b6", app.query_one("#panes").region.x), "the LCARS footer opens with a round cap on the boxes' line"
        assert app.query(FooterKey).first().region.x == foot_cap.region.right, "the LCARS footer opens with a round cap on the boxes' line"
        cap, fill = app.query_one("#footcap"), app.query_one("#side-fill")
        assert (cap.region.x, cap.region.y, cap.region.width) == (0, app.query_one(Footer).region.y, app.query_one("#sidebar").region.width), \
            "the LCARS sidebar runs down to the last row"
        assert str(fill.render()).splitlines() == ["█ █ ███", "█ █   █", "███   █", "  █   █", "  █   █"], "the LCARS sidebar ends in a big 47"
        assert fill.styles.content_align == ("center", "bottom"), "the big 47 sits in the middle of the sidebar, at its foot"
        assert app.query_one("#panel-details").region.x == app.query_one("#panes").region.right + 2, "LCARS leaves a gutter before the details"
        assert str(app.query_one("#status").render()) == rows.stardate(dt.datetime.fromtimestamp(1000.0)), "LCARS dates the last refresh in stardates"
        assert app.query_one("#condition").display, "LCARS shows the board's alert level"
        assert str(app.query_one("#condition").render()) == "\ue0b6 RED ALERT \ue0b4", "LCARS shows the board's alert level as a pill"
        assert str(app.query_one("#panel-changes").border_title) == "05-CAPTAIN'S LOG 1", "LCARS calls the changes the Captain's Log"
        assert "CAPTAIN'S" in str(app.query_one("#side-changes").render()), "LCARS calls the changes the Captain's Log"
        assert str(app.query_one("#panel-prs").border_title) == "04-CREW REPORTS 1", "LCARS calls the team PRs crew reports"
        assert "REPORTS" in str(app.query_one("#side-prs").render()), "LCARS calls the team PRs crew reports"
        titles = {key: str(app.query_one(f"#panel-{key}").border_title) for key in ("attention", "epics", "mine_prs", "mine_tickets", "details")}
        assert titles == {"attention": "03-BRIDGE ALERTS 1", "epics": "06-MISSIONS 1", "mine_prs": "07-MY REPORTS 1", "mine_tickets": "08-AWAY MISSIONS 2",
                          "details": "SENSOR READINGS"}, "LCARS names the boxes in Starfleet's words"
        key = app.query(FooterKey).first()
        assert (app.query_one(Footer).styles.background, key.styles.background) == (Color.parse(lcars["bg"]), Color.parse(lcars["line"])), \
            "LCARS turns the footer into a row of buttons"
        assert key.get_component_rich_style("footer-key--key").bgcolor.triplet.hex == lcars["accent"], "LCARS turns the footer into a row of buttons"
        buttons = list(app.query(".side"))
        assert app.query_one("#sidebar").display, "LCARS adds a sidebar button per box, lit for the focused one"
        assert [str(b.render()).split() [0] for b in buttons] == ["03", "04", "05", "06", "07", "08"], \
            "LCARS adds a sidebar button per box, lit for the focused one"
        assert [b.has_class("-on") for b in buttons] == [True, False, False, False, False, False], \
            "LCARS adds a sidebar button per box, lit for the focused one"
        await pilot.click("#side-changes")
        await pilot.pause()
        assert app.current_section == "changes", "a sidebar button focuses its box"
        assert app.query_one("#side-changes").has_class("-on"), "a sidebar button focuses its box"
        assert app.query_one("#panel-changes .fill").styles.background == Color.parse(lcars["accent"]), "the focused box lights its title pill"
        assert app.query_one("#panel-changes .name").styles.color == Color.parse(lcars["accent"]), "the focused box lights its title pill"
        edges = lambda box: [getattr(app.query_one(f"#panel-{box} .pbody").styles, f"border_{side}") for side in ("top", "left", "right", "bottom")]
        assert edges("prs") == [("", Color(0, 255, 0))] + [("round", Color.parse(lcars["line"]))] * 3, \
            "LCARS boxes keep their pill on top and a line on the other three sides"
        assert edges("changes")[1:] == [("round", Color.parse(lcars["accent"]))] * 3, "the focused box lights its lines"
        assert [corner.styles.color for corner in app.query("#panel-prs .edge")] == [Color.parse(lcars["line"])] * 2, \
            "LCARS boxes keep their pill on top and a line on the other three sides"
        assert [corner.styles.color for corner in app.query("#panel-changes .edge")] == [Color.parse(lcars["accent"])] * 2, \
            "the focused box lights its lines"
        await pilot.click("#pill-mine")
        await pilot.pause()
        assert (app.current_section, app.query_one(Tabs).active) == ("mine_prs", "tab-mine"), "a tab pill shows its tab"
        assert app.query_one("#panel-mine_tickets").region.bottom == app.query_one("#panel-details").region.bottom, "the LCARS columns end on the same row"
        assert [pill.has_class("-on") for pill in app.query(".tab-pill")] == [False, True], "the pill of the shown tab is lit"
        await pilot.press("1")
        await pilot.pause()
        assert [pill.has_class("-on") for pill in app.query(".tab-pill")] == [True, False], "the pill of the shown tab is lit"
        await pilot.press("7")
        await pilot.pause()
        assert [pill.has_class("-on") for pill in app.query(".tab-pill")] == [False, True], "the pill of the shown tab is lit"
        await pilot.press("5")
        await pilot.pause()
        assert app.screen.styles.background == Color.parse(lcars["bg"]), "t switches the TUI to LCARS"
        assert app.query_one("#panel-prs .fill").styles.background == Color.parse(lcars["line"]), "t switches the TUI to LCARS"
        assert lcars["accent"] in app.sections["prs"][0].detail, "the switch repaints the board"
    app = magi_app(cache, config_path=path)
    async with started(app) as pilot:
        assert app.screen.styles.background == Color.parse(lcars["bg"]), "the saved theme applies on start"
        await pick_theme(pilot, "picard")
        assert app.query_one("#panel-prs .fill").styles.background == Color.parse(theme.THEMES["picard"]["line"]), "the picard LCARS has its own colours"
        assert app.query_one("#sidebar").display, "the picard LCARS keeps the LCARS frame"
        await pick_theme(pilot, "default")
        assert app.screen.styles.background == Color.parse(theme.THEMES["default"]["bg"]), "t switches back to the default theme"
        assert str(app.query_one("#panel-prs").border_title) == "[4] team prs 1", "the default theme keeps its titles, states and header"
        assert "red CI · conflict" in app.query_one("#list-prs").get_option_at_index(1).prompt.plain, \
            "the default theme keeps its titles, states and header"
        assert str(app.query_one("#top .brand").render()) == "MAGI", "the default theme keeps its titles, states and header"
        assert not app.query_one("#sidebar").display, "the default theme keeps its titles, states and header"
        assert app.query_one(Tabs).display and not app.query_one("#pills").display, "the default theme keeps its tabs"
        assert not any(title.display for title in app.query(".ptitle")), "the default theme keeps its bordered titles"
        assert app.query_one("#panel-prs").styles.border_top[0] == "round", "the default theme keeps its bordered titles"
        assert not app.query_one("#condition").display, "the default theme drops the LCARS words"
        assert str(app.query_one("#panel-changes").border_title) == "[5] changes 1", "the default theme drops the LCARS words"
        assert str(app.query_one("#status").render()).startswith("updated "), "the default theme drops the LCARS words"
        assert app.query_one("#list-prs").get_option_at_index(0).prompt.plain == "── on the author (1) ──", \
            "the default theme drops the LCARS words and writes the turn groups in lowercase"
    app = magi_app(cache, load=failing_load, clock=lambda: 5000.0, config_path=path)
    async with started(app) as pilot:
        await pick_theme(pilot, "okuda")
        assert "refresh failed" in str(app.query_one("#status").render()), "switching the theme keeps a failed refresh visible"


@pytest.mark.usefixtures("default_theme")
def test_lcars_theme(cache):
    asyncio.run(lcars_theme(cache))


async def lcars_edit(cache):
    app = magi_app(cache, theme="okuda", edit_config=True)
    async with started(app) as pilot:
        app.screen.query_one("#config-team", Input).value = "alice bob, carol"
        await pilot.click("#config-save")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert json.loads(app.config_path.read_text())["theme"] == "okuda", "editing the config keeps the saved theme"


@pytest.mark.usefixtures("default_theme")
def test_lcars_edit(cache):
    asyncio.run(lcars_edit(cache))


async def refreshing_status(cache, name):
    release = threading.Event()
    def slow_load():
        release.wait(5)
        return board([PR_ONE])
    app = magi_app(cache, load=slow_load, theme=name)
    async with app.run_test(size=(160, 40)) as pilot:
        try:
            await pilot.pause()
            status = str(app.query_one("#status").render())
        finally:
            release.set()
        await app.workers.wait_for_complete()
    return status


@pytest.mark.usefixtures("default_theme")
@pytest.mark.parametrize("name, expected", [("okuda", "ENGAGING WARP DRIVE…"), ("default", "refreshing…")])
def test_refreshing_status(cache, name, expected):
    assert asyncio.run(refreshing_status(cache, name)) == expected, "LCARS refreshes by engaging warp drive, the default theme says refreshing"


async def lcars_condition(cache):
    lcars = theme.THEMES["okuda"]
    app = magi_app(cache, theme="okuda")
    async with started(app) as pilot:
        assert app.query_one("#elbow-logo").styles.background == app.query_one("#bar").styles.background, "the logo sits on the elbow's colour"
        for tone, label in zip(ALERT_PRS, ("CONDITION GREEN", "YELLOW ALERT", "RED ALERT")):
            app.show_board(board([ALERT_PRS[tone]]), 1000.0)
            await pilot.pause()
            shown, color = app.query_one("#condition").render(), Color.parse(lcars[tone])
            assert (shown.plain, [(span.style.foreground, span.style.background) for span in shown.spans]) == \
                (f"\ue0b6 {label} \ue0b4", [(color, None), (Color.parse(lcars["title"]), color), (color, None)]), \
                "LCARS shows the alert level as a green, yellow or red pill"
            frame = Color.parse(lcars["bad" if tone == "bad" else "accent"])
            assert (app.query_one("#bar").styles.background, app.query_one("#elbow").render().spans[0].style.foreground) == (frame, frame), \
                "RED ALERT turns the LCARS frame red, and it turns back when the alert drops"


@pytest.mark.usefixtures("default_theme")
def test_lcars_condition_colors(cache):
    asyncio.run(lcars_condition(cache))


async def long_boxes(cache):
    epics = [make_epic(key=f"ACME-{n}") for n in range(15)]
    full = {**board([PR_ONE]), "epics": epics, "tickets_by_epic": {e.key: TICKETS for e in epics},
            "attention": board([PR_ONE])["attention"] * 20}
    async with started(magi_app(cache, load=lambda: full)) as pilot:
        for name in ("default", "okuda"):
            await pick_theme(pilot, name)
            for box in ("attention", "epics"):
                panel, body, rows = (pilot.app.query_one(f"#panel-{box}{part}") for part in ("", " .pbody", f" #list-{box}"))
                assert rows.max_scroll_y > 0, f"a full {box} box scrolls in the {name} theme"
                assert body.region.bottom <= panel.region.bottom, f"a full {box} box keeps its bottom line in the {name} theme"


@pytest.mark.usefixtures("default_theme")
def test_full_boxes_scroll(cache):
    asyncio.run(long_boxes(cache))


def test_lcars_palettes():
    assert {name: theme.THEMES[name]["accent"] for name in theme.LCARS} == {"okuda": "#eb943a", "picard": "#37a6d1"}, \
        "LCARS comes in Okuda's classic and Picard colours"
    assert all(theme.THEMES[name].keys() == theme.THEMES["default"].keys() for name in theme.LCARS), "every LCARS palette names every colour"


async def theme_picker(cache):
    app = magi_app(cache)
    path = app.config_path
    async with started(app) as pilot:
        await pilot.press("t")
        await pilot.pause()
        choices = app.screen.query_one("#theme-list", OptionList)
        assert isinstance(app.screen, ThemeScreen), "t opens the theme picker"
        assert [choices.get_option_at_index(i).id for i in range(choices.option_count)] == ["default", "okuda", "picard", "nerv", "eva01", "cyberpunk"], \
            "the theme picker offers the default theme, the two LCARS ones, the two NERV ones and Cyberpunk"
        assert [choices.get_option_at_index(i).prompt for i in (3, 4)] == ["NERV Magi", "NERV - EVA 01"], "the theme picker names the NERV themes"
        assert choices.get_option_at_index(5).prompt == "Cyberpunk · Night City", "the theme picker names the Cyberpunk theme"
        assert choices.highlighted == 0, "the theme picker starts on the current theme"
        await pilot.press("down", "escape")
        await pilot.pause()
        assert not isinstance(app.screen, ThemeScreen), "escape closes the theme picker"
        assert (theme.current, json.loads(path.read_text()).get("theme", "default")) == ("default", "default"), "escape keeps the theme"
        await pilot.press("t", "down", "down", "enter")
        await pilot.pause()
        assert not isinstance(app.screen, ThemeScreen), "enter applies the highlighted theme"
        assert (theme.current, json.loads(path.read_text())) == ("picard", {**SETTINGS, "theme": "picard"}), \
            "enter applies the highlighted theme and saves it in the config"


@pytest.mark.usefixtures("default_theme")
def test_theme_picker(cache):
    asyncio.run(theme_picker(cache))


def test_every_theme_is_offered_by_one_name():
    assert screens.THEME_LABELS.keys() == theme.THEMES.keys(), "the picker offers every theme, each under its own label"
    assert set(theme.DROPPED.values()) <= theme.THEMES.keys(), "a dropped theme reads as one still offered"


@pytest.mark.parametrize("saved, started", [("lcars", "okuda"), ("voyager", "okuda"), ("magi", "nerv"), ("nerv", "nerv"),
                                            ("picard", "picard"), ("gone", "default")])
def test_a_saved_theme_reads_as_one_still_offered(saved, started):
    assert theme.offered(saved) == started, "an old or unknown saved theme reads as one still offered"


async def saved_theme_start(cache):
    app = magi_app(cache, theme="lcars")
    async with app.run_test() as pilot:
        await pilot.pause()
        return theme.current, app.settings.theme


@pytest.mark.usefixtures("default_theme")
def test_an_old_saved_theme_still_starts(cache):
    assert asyncio.run(saved_theme_start(cache)) == ("okuda", "okuda"), "an old saved theme starts as the one still offered"


@pytest.mark.usefixtures("default_theme")
def test_an_unknown_theme_keeps_the_current_one():
    theme.use_theme("okuda")
    with pytest.raises(KeyError):
        theme.use_theme("gone")
    assert (theme.current, theme.COLORS["accent"]) == ("okuda", theme.THEMES["okuda"]["accent"]), "an unknown theme changes nothing"


def test_no_logo_without_graphics(cache, monkeypatch, default_theme):
    monkeypatch.setattr(screens, "GRAPHICS", False)

    async def run():
        async with started(magi_app(cache)) as pilot:
            for name in ("default", "okuda", "nerv"):
                await pick_theme(pilot, name)
                assert not any(pilot.app.query_one(logo).display for logo in ("#top #logo", "#nerv-logo", "#elbow-logo")), \
                    f"a terminal without Sixel or Kitty graphics shows no logo in the {name} theme"
                assert pilot.app.query_one("#top .brand").display, f"a terminal without Sixel or Kitty graphics shows the name instead in the {name} theme"

    asyncio.run(run())


@pytest.mark.parametrize("name", ["okuda", "nerv"])
def test_framed_pr_rows_fit(cache, default_theme, name):
    async def run():
        async with started(magi_app(cache, load=lambda: board([PR_ONE, PR_TWO]), theme=name), size=(180, 50)) as pilot:
            listing = pilot.app.query_one("#list-prs", OptionList)
            room = listing.scrollable_content_region.width
            return room, [listing.get_option_at_index(i).prompt.cell_len for i in range(listing.option_count)]

    room, rows = asyncio.run(run())
    assert rows and all(width <= room for width in rows), f"a PR row fits its box in a 180-column terminal: {rows} in {room}"


def test_pr_rows_follow_their_box_when_it_resizes(cache, default_theme):
    async def run():
        async with started(magi_app(cache, load=lambda: board([PR_ONE, PR_TWO])), size=(160, 50)) as pilot:
            listing = pilot.app.query_one("#list-prs", OptionList)
            row = lambda: listing.get_option_at_index(1).prompt
            before = (listing.scrollable_content_region.width, row().cell_len)
            await pilot.resize_terminal(200, 50)
            for _ in range(50):
                await pilot.pause()
                if row().cell_len == listing.scrollable_content_region.width:
                    break
            return before, (listing.scrollable_content_region.width, row().cell_len), row().plain

    before, after, plain = asyncio.run(run())
    assert before[0] == before[1] and after[0] == after[1] and after[0] > before[0], \
        f"a PR row fills its box, before and after the terminal resizes: {before} then {after}"
    assert plain.rstrip().endswith(" app"), "the repo stays at the right edge after a resize"
