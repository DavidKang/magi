"""The software factory's stage files and herdr's agents, both read locally."""

import datetime as dt
import json
import re
import subprocess

from ..domain.factory import Agent, Stage
from ..domain.keys import TICKET_KEY
from . import paths, process

# herdr answers from its local server at once; a herdr that hangs must not hold the factory box.
HERDR_TIMEOUT = 5


def stages():
    found = []
    for path in sorted(paths.FACTORY_DIR.glob("*.json")):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):  # gone since listed, unreadable, cut, or not utf-8
            continue
        # The key goes into a link: only a Jira key gets that far.
        if isinstance(record, dict) and re.fullmatch(TICKET_KEY, str(record.get("key"))) and isinstance(record.get("stage"), str):
            found.append(Stage(record["key"], record["stage"], text(record.get("detail")) or "", since(record.get("updated_at"))))
    return found


def text(value):
    return value if isinstance(value, str) else None


def since(at):
    try:
        found = dt.datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return None
    return found if found.tzinfo else found.replace(tzinfo=dt.timezone.utc)


def agents():
    # herdr is optional: Magi runs without it, and a herdr that cannot answer reads as no sessions.
    try:
        listed = process.run_json(["herdr", "agent", "list"], timeout=HERDR_TIMEOUT)["result"]["agents"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return []
    return [Agent(agent["cwd"].rstrip("/").rpartition("/")[2], text(agent.get("agent_status")))
            for agent in listed if isinstance(agent, dict) and isinstance(agent.get("cwd"), str)]
