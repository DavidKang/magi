import tempfile
from pathlib import Path

import pytest

from builders import PR_ONE, ROOT, STATED, board
from tarkon import config
from tarkon.adapters import paths, process
from tarkon.html import page as web
from tarkon.tui import app as app_module


def test_brand():
    template = (Path(web.__file__).with_name("template.html")).read_text()
    assert "<title>TARKON</title>" in template, "the page is branded TARKON"
    assert "tarkon = \"tarkon.cli:main\"" in (ROOT / "pyproject.toml").read_text(), "the command is tarkon"


@pytest.mark.usefixtures("settings")
def test_data_paths():
    home = Path.home()
    assert paths.REFRESH_FILES["state"] == home / ".local/state/tarkon/state.json", "state lives in ~/.local/state/tarkon"
    assert web.OUT == home / ".local/state/tarkon/board.html", "the html page lives next to the state"
    assert app_module.CACHE == home / ".cache/tarkon/cache.json", "the TUI cache lives in ~/.cache/tarkon"
    assert paths.REFRESH_FILES["prs"].parent == home / ".cache/tarkon", "the TUI cache lives in ~/.cache/tarkon"
    assert config.PATH == home / ".config/tarkon/config.json", "settings live in ~/.config/tarkon"
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "missing" / "board.html"
        found = {**board([PR_ONE]), "merged_by_ticket": {}, "now": {"prs": {}}}
        path, web.OUT = web.OUT, out
        try:
            result = web.build(lambda settings: found, STATED)
        finally:
            web.OUT = path
        assert out.exists(), "the html page is written into a folder created on demand"
        assert result["out"] == out, "the html page is written into a folder created on demand"
        page = out.read_text().lower()
        assert "worktree" not in page, "the html page has no worktrees or herdr"
        assert "herdr" not in page, "the html page has no worktrees or herdr"
    assert not hasattr(process, "fetch_worktrees"), "nothing scans ~/projects or calls herdr"
    assert not hasattr(process, "herdr_workspaces"), "nothing scans ~/projects or calls herdr"

