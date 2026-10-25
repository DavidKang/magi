"""Entry point: tarkon opens the TUI, `config` its settings panel."""

import sys

from .adapters import github, jira, paths, process
from .adapters.clock import SystemClock
from .adapters.storage import JsonFiles
from .application.refresh import Refresh

USAGE = """usage: tarkon [config]

  tarkon         open the board
  tarkon config  open the settings panel"""


def refresh():
    """The refresh wired to the real Jira, GitHub, files and clock."""
    return Refresh(jira, github, JsonFiles(paths.REFRESH_FILES), SystemClock(), process.parallel)


def main():
    args = sys.argv[1:]
    if args in (["-h"], ["--help"]):
        print(USAGE)
        return
    if args not in ([], ["config"]):
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    missing = process.missing_tools()
    if missing:
        sys.exit("\n".join(missing))
    from .tui.app import main as run

    run(refresh().collect, edit_config=args == ["config"])
