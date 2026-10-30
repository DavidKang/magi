"""The files the TUI and magi web share beside the cache: the board, the mark a refresh leaves as it starts, the snoozes and the page."""

from ..adapters import paths, storage
from . import web
from .boxes import NUMBERS, SECTIONS

# A refresh costs about 7-8 s, 2-8 of GitHub's 5000 GraphQL points an hour and two REST calls per PR in conflict, after scripts/profile_refresh.py.
REFRESH_SECONDS = 5 * 60
REFRESH_COOLDOWN = 30
CACHE = paths.CACHE_DIR / "cache.json"
# Seen marks and snoozes kept their shape through these storage versions, so an upgrade keeps them instead of dropping them.
KEPT_UPGRADES = {4: lambda saved: saved, 5: lambda saved: saved, 6: lambda saved: saved, 7: lambda saved: saved}
SNOOZABLE = ("prs",)


def save_board(cache, at, board):
    storage.write(cache, {"at": at, "board": board})


def marked(stamp):
    """When the last refresh started, by its mark; None when none has."""
    return float(stamp.read_text()) if stamp.exists() else None


def last_started(saved, stamp):
    """When the last refresh started: the saved board's, or a newer one's still running; None before any."""
    started = [saved["at"]] if saved else []
    mark = marked(stamp)
    if mark is not None:
        started.append(mark)
    return max(started, default=None)


def mark_start(stamp, at):
    storage.write_text(stamp, str(at))


def read_snoozed(path):
    saved = storage.read(path, KEPT_UPGRADES)
    # Snoozes saved for a box that is gone are dropped with it.
    return {key: saved["snoozed"].get(key, {}) if saved else {} for key in SNOOZABLE}


def refresh_mark(cache):
    """Left beside the cache as a refresh starts, so another magi, TUI or web, waits for it instead of fetching the board too."""
    return cache.with_name("last-refresh")


def snoozes(cache):
    return cache.with_name("snoozed.json")


def page(cache):
    """The board as a web page, written beside the cache."""
    return cache.with_name("board.html")


def write_page(path, board, settings, snoozed, at):
    """The board as a web page at path, with its own boxes and numbers, my prs and my tickets among them, without the snoozed rows nor the factory."""
    storage.write_text(path, web.page(board, settings, snoozed, at, SECTIONS, NUMBERS, REFRESH_SECONDS))
