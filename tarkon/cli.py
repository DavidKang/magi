"""Entry point: tarkon opens the TUI, `config` its settings panel, `html` writes the browser page."""

import sys

from .fetch import missing_tools


def main():
    missing = missing_tools()
    if missing:
        sys.exit("\n".join(missing))
    if sys.argv[1:] == ["html"]:
        from .html.page import main as run

        run()
    else:
        from .tui.app import main as run

        run(edit_config=sys.argv[1:] == ["config"])
