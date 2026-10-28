import os
import subprocess
import sys
from pathlib import Path

import pytest

from builders import ROOT
from magi import config
from magi.adapters import paths, process
from magi.tui import app as app_module


def test_brand():
    assert "magi = \"magi.cli:main\"" in (ROOT / "pyproject.toml").read_text(), "the command is magi"


def test_data_paths():
    home = Path.home()
    assert paths.REFRESH_FILES["state"] == home / ".local/state/magi/state.json", "state lives in ~/.local/state/magi"
    assert app_module.CACHE == home / ".cache/magi/cache.json", "the TUI cache lives in ~/.cache/magi"
    assert paths.REFRESH_FILES["prs"].parent == home / ".cache/magi", "the TUI cache lives in ~/.cache/magi"
    assert config.PATH == home / ".config/magi/config.json", "settings live in ~/.config/magi"
    assert not hasattr(process, "fetch_worktrees"), "nothing scans ~/projects for worktrees or lists herdr workspaces"
    assert not hasattr(process, "herdr_workspaces"), "nothing scans ~/projects for worktrees or lists herdr workspaces"


def test_the_data_kept_under_tarkon_moves_to_magi(tmp_path):
    for parent in (".config", ".local/state", ".cache"):
        (tmp_path / parent / "tarkon").mkdir(parents=True)
        (tmp_path / parent / "tarkon" / "kept.json").write_text(parent)
    (tmp_path / ".cache/magi").mkdir()
    subprocess.run([sys.executable, "-m", "magi"], capture_output=True, text=True, cwd=ROOT,
                   env={**os.environ, "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=15)
    for parent in (".config", ".local/state"):
        assert (tmp_path / parent / "magi" / "kept.json").read_text() == parent, f"{parent}/tarkon moves to {parent}/magi on start"
        assert not (tmp_path / parent / "tarkon").exists(), f"{parent}/tarkon moves to {parent}/magi on start"
    assert (tmp_path / ".cache/tarkon/kept.json").exists(), "an existing magi folder is never overwritten by the old tarkon one"
    assert not (tmp_path / ".cache/magi/kept.json").exists(), "an existing magi folder is never overwritten by the old tarkon one"


@pytest.mark.parametrize("args", [["html"], ["config", "extra"], ["--verbose"]])
def test_an_unsupported_argument_shows_the_usage(tmp_path, args):
    result = subprocess.run([sys.executable, "-m", "magi", *args], capture_output=True, text=True, cwd=ROOT,
                            env={**os.environ, "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=15)
    assert result.returncode == 2, "an unsupported argument exits with the usage instead of opening the TUI"
    assert result.stderr.startswith("usage: magi [config]"), "an unsupported argument exits with the usage instead of opening the TUI"
    assert "gh not found" not in result.stderr, "the usage comes before checking for gh and acli"


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_shows_the_usage(tmp_path, flag):
    result = subprocess.run([sys.executable, "-m", "magi", flag], capture_output=True, text=True, cwd=ROOT,
                            env={**os.environ, "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=15)
    assert (result.returncode, result.stderr) == (0, ""), "--help prints the usage and exits cleanly"
    assert result.stdout.startswith("usage: magi [config]"), "--help prints the usage and exits cleanly"
    assert "magi config" in result.stdout, "--help prints the usage and exits cleanly"
