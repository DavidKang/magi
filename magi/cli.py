"""Entry point: magi opens the TUI, `config` its settings panel, `web` the board's web page."""

import sys

from .adapters import factory, github, jira, paths, process
from .adapters.clock import SystemClock
from .adapters.storage import JsonFiles
from .application.factory import Factory
from .application.refresh import Refresh
from .application.upgrades import UPGRADES

USAGE = """usage: magi [config|web]

  magi         open the board
  magi config  open the settings panel
  magi web     refresh the board every 5 minutes without the TUI and open its web page"""


def refresh():
    """The refresh wired to the real Jira, GitHub, files and clock."""
    return Refresh(jira, github, JsonFiles(paths.REFRESH_FILES, UPGRADES), SystemClock(), process.parallel)


def main():
    args = sys.argv[1:]
    if args in (["-h"], ["--help"]):
        print(USAGE)
        return
    if args not in ([], ["config"], ["web"]):
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    paths.move_old_dirs()
    missing = process.missing_tools()
    if missing:
        sys.exit("\n".join(missing))
    wired = refresh()
    if args == ["web"]:
        from .tui.web_watch import watch

        sys.exit(watch(wired.collect))
    from .tui.app import main as run

    box = Factory(factory)
    run(wired.collect, wired.ticket, box.collect, box.focus, edit_config=args == ["config"])
