import asyncio
import json

import pytest
from textual.color import Color
from textual.widgets import Footer, Input, OptionList, Static, Tabs
from textual.widgets._footer import FooterKey

import datetime as dt

from builders import PR_ONE, SETTINGS, TICKETS, board, failing_load, make_epic, make_pr, settings_file
from tarkon import rows
from tarkon.tui import theme
from tarkon.tui.app import TarkonApp
from tarkon.tui import screens
from tarkon.tui.screens import ThemeScreen
from textual_image.widget import get_cell_size


async def pick_theme(pilot, name):
    await pilot.press("t")
    await pilot.pause()
    choices = pilot.app.screen.query_one("#theme-list", OptionList)
    choices.highlighted = choices.get_option_index(name)
    await pilot.press("enter")
    await pilot.pause()


async def lcars_theme(cache):
    path = settings_file(cache)
    lcars = theme.THEMES["okuda"]
    app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, clock=lambda: 1000.0, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.screen.styles.background == Color.parse(theme.THEMES["default"]["bg"]), "a config without a theme starts with the default one"
        assert not any(app.query_one(f"#{name}").display for name in ("elbow", "bar", "sidebar", "condition", "pills")), "the default theme has no LCARS frame"
        assert app.query_one(Tabs).display, "the default theme keeps its tabs"
        assert app.query_one("#top #logo").display and not app.query_one("#elbow-logo").display, "the default theme keeps its logo in the masthead"
        assert not any(app.query_one(f"#{name}").display for name in ("footcap", "foot-cap")) and app.query_one(Footer).region.x == 0, \
            "the default theme keeps its footer"
        assert not any(title.display for title in app.query(".ptitle")), "the default theme keeps its bordered titles"
        await pick_theme(pilot, "okuda")
        assert app.query_one("#elbow").display, "LCARS frames the header with an elbow"
        assert app.query_one("#bar").display, "LCARS frames the header with an elbow"
        assert str(app.query_one("#top .brand").render()) == "TARKON", "LCARS frames the header with an elbow"
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
        assert [str(s.render()) for s in app.query_one("#panel-details").query(".ptitle Static")][3] == "DETAILS", "the details panel has a pill title too"
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
        assert app.query_one("#list-prs").get_option_at_index(0).prompt.plain == "── PRIORITY ONE (1) ──", "LCARS puts old team PRs first"
        assert str(app.query_one("#panel-prs").border_title) == "04-CREW REPORTS 1", "LCARS calls the team PRs crew reports"
        assert "REPORTS" in str(app.query_one("#side-prs").render()), "LCARS calls the team PRs crew reports"
        assert str(app.query_one("#panel-details").border_title) == "DETAILS", "LCARS titles panels with a two-digit code in capitals"
        key = app.query(FooterKey).first()
        assert (app.query_one(Footer).styles.background, key.styles.background) == (Color.parse(lcars["bg"]), Color.parse(lcars["line"])), \
            "LCARS turns the footer into a row of buttons"
        assert key.get_component_rich_style("footer-key--key").bgcolor.triplet.hex == lcars["accent"], "LCARS turns the footer into a row of buttons"
        assert "◖ AWAITING REVIEW " in app.query_one("#list-prs").get_option_at_index(1).prompt.plain, "LCARS shows review and CI states as pills"
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
        assert json.loads(path.read_text()) == {**SETTINGS, "theme": "okuda"}, "the theme is saved in the config"
    app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, clock=lambda: 1000.0, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.screen.styles.background == Color.parse(lcars["bg"]), "the saved theme applies on start"
        for name in ("picard",):
            await pick_theme(pilot, name)
            assert app.query_one("#panel-prs .fill").styles.background == Color.parse(theme.THEMES[name]["line"]), f"the {name} LCARS has its own colours"
            assert app.query_one("#sidebar").display, f"the {name} LCARS keeps the LCARS frame"
            assert json.loads(path.read_text())["theme"] == name, "the picked theme is saved in the config"
        await pick_theme(pilot, "default")
        assert app.screen.styles.background == Color.parse(theme.THEMES["default"]["bg"]), "t switches back to the default theme"
        assert json.loads(path.read_text())["theme"] == "default", "t switches back to the default theme"
        assert str(app.query_one("#panel-prs").border_title) == "[4] team prs 1", "the default theme keeps its titles, states and header"
        assert "awaiting review" in app.query_one("#list-prs").get_option_at_index(0).prompt.plain, \
            "the default theme keeps its titles, states and header"
        assert str(app.query_one("#top .brand").render()) == "TARKON", "the default theme keeps its titles, states and header"
        assert not app.query_one("#sidebar").display, "the default theme keeps its titles, states and header"
        assert app.query_one(Tabs).display and not app.query_one("#pills").display, "the default theme keeps its tabs"
        assert not any(title.display for title in app.query(".ptitle")), "the default theme keeps its bordered titles"
        assert app.query_one("#panel-prs").styles.border_top[0] == "round", "the default theme keeps its bordered titles"
        assert not app.query_one("#condition").display, "the default theme drops the LCARS words"
        assert str(app.query_one("#panel-changes").border_title) == "[5] changes 1", "the default theme drops the LCARS words"
        assert str(app.query_one("#status").render()).startswith("updated "), "the default theme drops the LCARS words"
        assert app.query_one("#list-prs").get_option_at_index(0).id == "0", "the default theme drops the LCARS words"
    app = TarkonApp(load=failing_load, opener=print, copier=print, clock=lambda: 5000.0, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pick_theme(pilot, "okuda")
        assert "refresh failed" in str(app.query_one("#status").render()), "switching the theme keeps a failed refresh visible"


@pytest.mark.usefixtures("settings", "default_theme")
def test_lcars_theme(cache):
    asyncio.run(lcars_theme(cache))


async def lcars_edit(cache):
    path = settings_file(cache, {**SETTINGS, "theme": "okuda"})
    app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, cache=cache, config_path=path, edit_config=True)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        app.screen.query_one("#config-team", Input).value = "alice bob, carol"
        await pilot.click("#config-save")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert json.loads(path.read_text())["theme"] == "okuda", "editing the config keeps the saved theme"


@pytest.mark.usefixtures("settings", "default_theme")
def test_lcars_edit(cache):
    asyncio.run(lcars_edit(cache))


async def lcars_condition(cache, prs):
    path = settings_file(cache, {**SETTINGS, "theme": "okuda"})
    app = TarkonApp(load=lambda: board(prs), opener=print, copier=print, clock=lambda: 1000.0, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        shown = app.query_one("#condition").render(), app.query_one("#bar").styles.background, app.query_one("#elbow").render().spans[0].style
        assert app.query_one("#elbow-logo").styles.background == app.query_one("#bar").styles.background, "the logo sits on the elbow's colour"
        app.show_board(board([make_pr(review_decision="APPROVED", ci="passing", mergeable="MERGEABLE")]), 1000.0)
        await pilot.pause()
        return *shown, app.query_one("#bar").styles.background, app.query_one("#elbow").render().spans[0].style.foreground


@pytest.mark.usefixtures("default_theme")
@pytest.mark.parametrize("pr, label, tone", [
    (make_pr(review_decision="APPROVED", ci="passing", mergeable="MERGEABLE"), "CONDITION GREEN", "ok"),
    (make_pr(ci="passing", mergeable="MERGEABLE"), "YELLOW ALERT", "warn"),
    (make_pr(), "RED ALERT", "bad"),
    (make_pr(author={"login": "bob"}), "YELLOW ALERT", "warn")])
def test_lcars_condition_colors(cache, pr, label, tone):
    shown, bar, elbow = asyncio.run(lcars_condition(cache, [pr]))[:3]
    lcars = theme.THEMES["okuda"]
    color = Color.parse(lcars[tone])
    assert (shown.plain, [(span.style.foreground, span.style.background) for span in shown.spans]) == \
        (f"\ue0b6 {label} \ue0b4", [(color, None), (Color.parse(lcars["title"]), color), (color, None)]), \
        "LCARS shows the alert level as a green, yellow or red pill"
    frame = Color.parse(lcars["bad"] if label == "RED ALERT" else lcars["accent"])
    assert (bar, elbow.foreground) == (frame, frame), "RED ALERT turns the LCARS frame red"


async def long_boxes(cache, name):
    epics = [make_epic(key=f"ACME-{n}") for n in range(15)]
    full = {**board([PR_ONE]), "epics": epics, "tickets_by_epic": {e.key: TICKETS for e in epics},
            "attention": board([PR_ONE])["attention"] * 20}
    app = TarkonApp(load=lambda: full, opener=print, copier=print, clock=lambda: 1000.0, cache=cache,
                   config_path=settings_file(cache, {**SETTINGS, "theme": name}))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        for box in ("attention", "epics"):
            panel, body, rows = (app.query_one(f"#panel-{box}{part}") for part in ("", " .pbody", f" #list-{box}"))
            assert rows.max_scroll_y > 0, f"a full {box} box scrolls in the {name} theme"
            assert body.region.bottom <= panel.region.bottom, f"a full {box} box keeps its bottom line in the {name} theme"


@pytest.mark.usefixtures("default_theme")
@pytest.mark.parametrize("name", ["default", *theme.LCARS])
def test_full_boxes_scroll(cache, name):
    asyncio.run(long_boxes(cache, name))


@pytest.mark.usefixtures("default_theme")
def test_lcars_frame_follows_the_alert(cache):
    *_, bar, elbow = asyncio.run(lcars_condition(cache, [make_pr()]))
    accent = Color.parse(theme.THEMES["okuda"]["accent"])
    assert (bar, elbow) == (accent, accent), "the LCARS frame turns back from red when the alert drops"


def test_lcars_palettes():
    assert {name: theme.THEMES[name]["accent"] for name in theme.LCARS} == {"okuda": "#eb943a", "picard": "#37a6d1"}, \
        "LCARS comes in Okuda's classic and Picard colours"
    assert all(theme.THEMES[name].keys() == theme.THEMES["default"].keys() for name in theme.LCARS), "every LCARS palette names every colour"


async def theme_picker(cache):
    path = settings_file(cache)
    app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, clock=lambda: 1000.0, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.press("t")
        await pilot.pause()
        choices = app.screen.query_one("#theme-list", OptionList)
        assert isinstance(app.screen, ThemeScreen), "t opens the theme picker"
        assert [choices.get_option_at_index(i).id for i in range(choices.option_count)] == ["default", "okuda", "picard"], \
            "the theme picker offers the default theme and the two LCARS ones"
        assert choices.highlighted == 0, "the theme picker starts on the current theme"
        await pilot.press("down", "escape")
        await pilot.pause()
        assert not isinstance(app.screen, ThemeScreen), "escape closes the theme picker"
        assert (theme.current, json.loads(path.read_text()).get("theme", "default")) == ("default", "default"), "escape keeps the theme"
        await pilot.press("t", "down", "down", "enter")
        await pilot.pause()
        assert not isinstance(app.screen, ThemeScreen), "enter applies the highlighted theme"
        assert (theme.current, json.loads(path.read_text())["theme"]) == ("picard", "picard"), "enter applies the highlighted theme and saves it"


@pytest.mark.usefixtures("settings", "default_theme")
def test_theme_picker(cache):
    asyncio.run(theme_picker(cache))
