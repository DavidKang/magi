"""magi web: the board's web page kept fresh without the TUI, refreshed as often as the TUI refreshes and opened in the browser once."""

import datetime as dt
import time

from .. import config
from ..adapters import storage
from ..application.refresh import saved_board
from .app import error_message, write_page
from .board_files import (CACHE, REFRESH_COOLDOWN, REFRESH_SECONDS, mark_start, marked, page, read_snoozed, refresh_mark,
                          save_board, snoozes)
from .system import open_in_browser

# Seconds magi web wakes past a refresh's due time: a running TUI's tick, due at the same moment, starts its refresh first.
TUI_FIRST = 3


def watch(collect, cache=CACHE, config_path=config.PATH, opener=open_in_browser, clock=time.time, sleep=time.sleep, say=print):
    """Refreshes the board with collect each interval and rewrites its page until ctrl-c; what it returns is the reason it could not."""
    settings = config.load(config_path)
    if settings is None:
        return "no settings yet: run magi config first"
    stamp, opened, began = refresh_mark(cache), False, clock()
    try:
        while True:
            settings = reloaded(config_path, settings)
            saved = storage.read(cache)
            # A running TUI refreshes on its own and saves where this reads: the board is fetched only once nobody has for an interval.
            fresh = refresh(collect, settings, cache, stamp, clock, say) if clock() >= due(saved, stamp, began) else None
            saved = fresh or saved
            # The TUI writes the page after its own refreshes: magi web writes it after its own, and once to open it.
            if saved and (fresh or not opened):
                try:
                    write_page(page(cache), saved_board(saved["board"]), settings, read_snoozed(snoozes(cache)), saved["at"])
                except OSError as error:
                    say(f"web page not written: {error}")
                else:
                    if not opened:
                        opener(str(page(cache)))
                        opened = True
            wait = due(saved, stamp, began) - clock()
            sleep(wait if wait > 0 else REFRESH_SECONDS)
    except KeyboardInterrupt:
        return None


def reloaded(path, settings):
    """The settings as magi config left them, so a changed team is the one fetched next; the ones it had while they are gone or half written."""
    try:
        return config.load(path) or settings
    except (ValueError, TypeError):
        return settings


def due(saved, stamp, began):
    """When the next refresh is due: an interval after the last one started, here or in a TUI, and a moment more.

    A mark left before magi web began may be a refresh that died with its magi: like the TUI, it waits only the cooldown on it."""
    started = marked(stamp)
    times = [saved["at"] + REFRESH_SECONDS] if saved else []
    if started is not None:
        times.append(started + (REFRESH_COOLDOWN if started < began else REFRESH_SECONDS))
    return max(times) + TUI_FIRST if times else 0


def refresh(collect, settings, cache, stamp, clock, say):
    """The board fetched and saved as the TUI saves it, read back; None when the fetch or the save failed."""
    started = clock()
    try:
        mark_start(stamp, started)
        board = collect(settings)
        save_board(cache, started, board)
    except Exception as error:
        say(f"refresh failed: {error_message(error)}")
        return None
    say(f"board refreshed at {dt.datetime.fromtimestamp(started):%H:%M}, again every {REFRESH_SECONDS // 60} minutes; ctrl-c stops")
    return storage.read(cache)
