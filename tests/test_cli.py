import os
import subprocess
import sys
from pathlib import Path

import pytest

from builders import ROOT
from tarkon import config
from tarkon.adapters import paths, process
from tarkon.tui import app as app_module


def test_brand():
    assert "tarkon = \"tarkon.cli:main\"" in (ROOT / "pyproject.toml").read_text(), "the command is tarkon"


def test_data_paths():
    home = Path.home()
    assert paths.REFRESH_FILES["state"] == home / ".local/state/tarkon/state.json", "state lives in ~/.local/state/tarkon"
    assert app_module.CACHE == home / ".cache/tarkon/cache.json", "the TUI cache lives in ~/.cache/tarkon"
    assert paths.REFRESH_FILES["prs"].parent == home / ".cache/tarkon", "the TUI cache lives in ~/.cache/tarkon"
    assert config.PATH == home / ".config/tarkon/config.json", "settings live in ~/.config/tarkon"
    assert not hasattr(process, "fetch_worktrees"), "nothing scans ~/projects or calls herdr"
    assert not hasattr(process, "herdr_workspaces"), "nothing scans ~/projects or calls herdr"


@pytest.mark.parametrize("args", [["html"], ["config", "extra"], ["--verbose"]])
def test_an_unsupported_argument_shows_the_usage(tmp_path, args):
    result = subprocess.run([sys.executable, "-m", "tarkon", *args], capture_output=True, text=True, cwd=ROOT,
                            env={**os.environ, "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=15)
    assert result.returncode == 2, "an unsupported argument exits with the usage instead of opening the TUI"
    assert result.stderr.startswith("usage: tarkon [config]"), "an unsupported argument exits with the usage instead of opening the TUI"
    assert "gh not found" not in result.stderr, "the usage comes before checking for gh and acli"


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_shows_the_usage(tmp_path, flag):
    result = subprocess.run([sys.executable, "-m", "tarkon", flag], capture_output=True, text=True, cwd=ROOT,
                            env={**os.environ, "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=15)
    assert (result.returncode, result.stderr) == (0, ""), "--help prints the usage and exits cleanly"
    assert result.stdout.startswith("usage: tarkon [config]"), "--help prints the usage and exits cleanly"
    assert "tarkon config" in result.stdout, "--help prints the usage and exits cleanly"
