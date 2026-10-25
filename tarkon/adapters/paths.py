"""Where Tarkon keeps its data: state in ~/.local/state/tarkon, caches in ~/.cache/tarkon."""

from pathlib import Path

STATE_DIR = Path.home() / ".local" / "state" / "tarkon"
CACHE_DIR = Path.home() / ".cache" / "tarkon"
# The files the refresh reads and writes, by the name it uses for them.
REFRESH_FILES = {"state": STATE_DIR / "state.json", "prs": CACHE_DIR / "prs.json", "updated": CACHE_DIR / "updated.json",
                 "my_tickets": CACHE_DIR / "my-tickets.json"}
