import asyncio
import json

from textual.widgets import Input
from textual_image.widget import Image

from builders import PR_ONE, SETTINGS, board, settings_file
from tarkon.tui import screens
from tarkon.tui.app import TarkonApp


async def first_run(cache):
    cache = cache.parent / "missing" / "cache.json"
    path, calls = cache.with_name("config.json"), []
    def load():
        calls.append(1)
        return board([PR_ONE])
    app = TarkonApp(load=load, opener=print, copier=print, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen.query_one("#logo"), Image), "the config panel shows the logo instead of the rocket"
        assert all("🚀" not in str(brand.render()) for brand in app.screen.query(".brand")), "the config panel shows the logo instead of the rocket"
        assert str(app.screen.query_one(".brand").render()) == "TARKON config", "the config panel is branded TARKON"
        inputs = {i.id.removeprefix("config-"): i for i in app.screen.query(Input)}
        assert sorted(inputs) == sorted(SETTINGS), "first run opens the config panel with the five fields"
        assert all(not i.value and i.placeholder for i in inputs.values()), "config fields start empty with a placeholder"
        assert calls == [], "board waits until the config is saved"
        assert not app.check_action("focus_filter", ()), "config panel hides the board keys on first run"
        assert not app.check_action("refresh", ()), "config panel hides the board keys on first run"
        assert not app.check_action("pick_theme", ()), "config panel hides the board keys on first run"
        assert app.screen.check_action("save", ()), "config panel hides the board keys on first run"
        inputs["team"].value = "alice, bob"
        await pilot.click("#config-save")
        await pilot.pause()
        assert not path.exists(), "saving with empty fields is refused"
        assert any("Fill in every field" in n.message for n in app._notifications), "saving with empty fields is refused"
        for key, value in {"jira_project": "ACME", "github_user": "alice", "github_org": "acme",
                           "jira_url": "https://acme.atlassian.net"}.items():
            inputs[key].value = value
        await pilot.pause(0.3)
        await pilot.click("#config-save")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert json.loads(path.read_text()) == {**SETTINGS, "theme": "default"}, "saving writes the config"
        assert calls == [1], "saving opens the board"
        assert str(app.query_one("#panel-prs").border_title) == "[4] team prs 1", "saving opens the board"
        assert cache.exists(), "the TUI cache is written into a folder created on demand"


def test_first_run(cache):
    asyncio.run(first_run(cache))


async def edit(cache):
    path = settings_file(cache)
    app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, cache=cache, config_path=path, edit_config=True)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        inputs = {i.id.removeprefix("config-"): i for i in app.screen.query(Input)}
        assert app.screen.check_action("cancel", ()), "config command can be cancelled"
        assert inputs["team"].value == "alice, bob", "config command shows the saved values"
        assert inputs["jira_project"].value == "ACME", "config command shows the saved values"
        inputs["team"].value = "alice bob, carol"
        await pilot.click("#config-save")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert json.loads(path.read_text())["team"] == ["alice", "bob", "carol"], "config command saves the changes"
        assert str(app.query_one("#panel-prs").border_title) == "[4] team prs 1", "config command then opens the board"


def test_edit(cache):
    asyncio.run(edit(cache))


async def first_run_cancel(cache):
    path, calls = cache.with_name("config.json"), []
    app = TarkonApp(load=lambda: calls.append(1), opener=print, copier=print, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.click("#config-cancel")
        await pilot.pause()
        assert not app.is_running, "cancel on first run quits without saving or loading"
        assert not path.exists(), "cancel on first run quits without saving or loading"
        assert calls == [], "cancel on first run quits without saving or loading"


def test_first_run_cancel(cache):
    asyncio.run(first_run_cancel(cache))


async def edit_cancel(cache):
    path = settings_file(cache)
    app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, cache=cache, config_path=path, edit_config=True)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        app.screen.query_one("#config-team", Input).value = "zed"
        await pilot.click("#config-cancel")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert json.loads(path.read_text()) == {**SETTINGS, "theme": "default"}, "cancel keeps the saved config"
        assert str(app.query_one("#panel-prs").border_title) == "[4] team prs 1", "cancel goes to the board"


def test_edit_cancel(cache):
    asyncio.run(edit_cancel(cache))


def test_config_panel_without_graphics(cache, monkeypatch):
    monkeypatch.setattr(screens, "GRAPHICS", False)

    async def run():
        app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, cache=cache, config_path=cache.with_name("config.json"))
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.pause()
            assert not app.screen.query_one("#logo").display, "a terminal without Sixel or Kitty graphics shows no logo"
            assert app.screen.query_one(".brand").display, "a terminal without Sixel or Kitty graphics shows the name instead"

    asyncio.run(run())
