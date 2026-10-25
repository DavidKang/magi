"""Where Magi keeps its data: state in ~/.local/state/magi, caches in ~/.cache/magi."""

from pathlib import Path

STATE_DIR = Path.home() / ".local" / "state" / "magi"
CACHE_DIR = Path.home() / ".cache" / "magi"
# The files the refresh reads and writes, by the name it uses for them.
REFRESH_FILES = {"state": STATE_DIR / "state.json", "prs": CACHE_DIR / "prs.json", "updated": CACHE_DIR / "updated.json",
                 "my_tickets": CACHE_DIR / "my-tickets.json"}
# Magi was called Tarkon; its folders move once so the rename keeps settings, state and caches.
OLD_DIRS = [Path.home() / parent / "tarkon" for parent in (".config", ".local/state", ".cache")]


def move_old_dirs():
    for old in OLD_DIRS:
        new = old.with_name("magi")
        if old.is_dir() and not new.exists():
            old.rename(new)
