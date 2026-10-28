"""Who Magi tells that a refresh brought news: the multiplexer it runs in, found by the variable it sets in its panes."""

import subprocess
import threading

AGENT = ["--source", "magi", "--agent", "magi"]
# Herdr answers through a local socket at once; a herdr that takes longer is stuck, and the board must not wait on it.
TIMEOUT = 1


class Silent:
    """Nobody to tell."""

    def news(self):
        pass

    def leave(self):
        pass


class Herdr:
    """Herdr marks the workspace of an agent whose turn ended while you looked elsewhere, and plays its done sound."""

    def __init__(self, pane):
        # News runs on its own thread: leaving waits for it, or a late report would take the pane back after the release.
        self.pane, self.telling, self.left = pane, threading.Lock(), False

    def news(self):
        with self.telling:
            if not self.left:
                self.pane_commands(["report-agent", "--state", "working"], ["report-agent", "--state", "idle"])

    def leave(self):
        with self.telling:
            self.left = True
            self.pane_commands(["release-agent"])

    def pane_commands(self, *commands):
        """Each command in turn, until herdr is missing or takes too long: the rest would only wait on it again."""
        for command, *options in commands:
            # Its output would draw over the board. A herdr that is missing or stuck is no reason to stop.
            try:
                subprocess.run(["herdr", "pane", command, *AGENT, *options, self.pane], capture_output=True, check=False, timeout=TIMEOUT)
            except (OSError, subprocess.TimeoutExpired):
                return


# The variable each multiplexer sets in its panes, and who tells it; another one is one more row.
NOTIFIERS = {"HERDR_PANE_ID": Herdr}


def notifier(environ):
    return next((tell(environ[name]) for name, tell in NOTIFIERS.items() if environ.get(name)), Silent())
