import asyncio
import json

import pytest
from textual.color import Color
from textual.widgets import Input

from builders import PR_ONE, SETTINGS, board, failing_load, settings_file
from tarkon.tui import theme
from tarkon.tui.app import TarkonApp


async def lcars_theme(cache):
    path = settings_file(cache)
    lcars = theme.THEMES["lcars"]
    app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, clock=lambda: 1000.0, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.screen.styles.background == Color.parse(theme.THEMES["default"]["bg"]), "a config without a theme starts with the default one"
        assert not any(app.query_one(f"#{name}").display for name in ("elbow", "bar", "sidebar")), "the default theme has no LCARS frame"
        await pilot.press("t")
        await pilot.pause()
        assert app.query_one("#elbow").display, "LCARS frames the header with an elbow"
        assert app.query_one("#bar").display, "LCARS frames the header with an elbow"
        assert str(app.query_one("#top .brand").render()) == "TARKON", "LCARS frames the header with an elbow"
        assert str(app.query_one("#status").render()).startswith("STARDATE "), "LCARS frames the header with an elbow"
        assert str(app.query_one("#panel-prs").border_title) == "04-TEAM PRS 1", "LCARS titles panels with a two-digit code in capitals"
        assert str(app.query_one("#detail").parent.border_title) == "DETAILS", "LCARS titles panels with a two-digit code in capitals"
        assert "◖AWAITING REVIEW" in app.query_one("#list-prs").get_option_at_index(0).prompt.plain, "LCARS shows review and CI states as pills"
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
        assert app.screen.styles.background == Color.parse(lcars["bg"]), "t switches the TUI to LCARS"
        assert app.query_one("#panel-prs").styles.border_top == ("panel", Color.parse(lcars["line"])), "t switches the TUI to LCARS"
        assert lcars["accent"] in app.sections["prs"][0].detail, "the switch repaints the board"
        assert json.loads(path.read_text()) == {**SETTINGS, "theme": "lcars"}, "the theme is saved in the config"
    app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, clock=lambda: 1000.0, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.screen.styles.background == Color.parse(lcars["bg"]), "the saved theme applies on start"
        await pilot.press("t")
        await pilot.pause()
        assert app.screen.styles.background == Color.parse(theme.THEMES["default"]["bg"]), "t switches back to the default theme"
        assert json.loads(path.read_text())["theme"] == "default", "t switches back to the default theme"
        assert str(app.query_one("#panel-prs").border_title) == "[4] team prs 1", "the default theme keeps its titles, states and header"
        assert "awaiting review" in app.query_one("#list-prs").get_option_at_index(0).prompt.plain, \
            "the default theme keeps its titles, states and header"
        assert str(app.query_one("#top .brand").render()) == "TARKON", "the default theme keeps its titles, states and header"
        assert not app.query_one("#sidebar").display, "the default theme keeps its titles, states and header"
    app = TarkonApp(load=failing_load, opener=print, copier=print, clock=lambda: 5000.0, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        assert "refresh failed" in str(app.query_one("#status").render()), "switching the theme keeps a failed refresh visible"


@pytest.mark.usefixtures("settings", "default_theme")
def test_lcars_theme(cache):
    asyncio.run(lcars_theme(cache))


async def lcars_edit(cache):
    path = settings_file(cache, {**SETTINGS, "theme": "lcars"})
    app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, cache=cache, config_path=path, edit_config=True)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        app.screen.query_one("#config-team", Input).value = "alice bob, carol"
        await pilot.click("#config-save")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert json.loads(path.read_text())["theme"] == "lcars", "editing the config keeps the saved theme"


@pytest.mark.usefixtures("settings", "default_theme")
def test_lcars_edit(cache):
    asyncio.run(lcars_edit(cache))
