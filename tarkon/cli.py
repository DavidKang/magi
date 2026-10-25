"""Entry point: tarkon opens the TUI, `config` its settings panel, `html` writes the browser page."""

import sys

from .adapters import github, jira, paths, process
from .adapters.clock import SystemClock
from .adapters.storage import JsonFiles
from .application.refresh import Refresh


def refresh():
    """The refresh wired to the real Jira, GitHub, files and clock."""
    return Refresh(jira, github, JsonFiles(paths.REFRESH_FILES), SystemClock(), process.parallel)


def main():
    missing = process.missing_tools()
    if missing:
        sys.exit("\n".join(missing))
    if sys.argv[1:] == ["html"]:
        from .html.page import main as run

        run(refresh().collect)
    else:
        from .tui.app import main as run

        run(refresh().collect, edit_config=sys.argv[1:] == ["config"])
