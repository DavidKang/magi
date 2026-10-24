"""Profile one real refresh: time per call, calls per tool, REST searches and GraphQL points.

Reads the real Jira and GitHub, but never writes the user's state or cache: state.json is copied to a scratch dir first.
Run: .venv/bin/python scripts/profile_refresh.py
"""

import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

from tarkon import board, config, fetch

calls = []
lock = threading.Lock()
original_run_json = fetch.run_json


def label(cmd):
    if cmd[0] == "acli":
        jql = cmd[cmd.index("--jql") + 1] if "--jql" in cmd else ""
        return f"acli {cmd[3]} " + (re.split(r"[ =(]", jql)[0] if jql else cmd[cmd.index("--fields") + 1][:20])
    if cmd[1:3] == ["search", "prs"]:
        return "gh search " + next((part for part in cmd[3:] if part.startswith(("--author", "--merged", "user-review"))), "keys")
    return " ".join(cmd[:3])


def timed_run_json(cmd):
    start = time.perf_counter()
    try:
        return original_run_json(cmd)
    finally:
        with lock:
            calls.append((label(cmd), start, time.perf_counter()))


def rate_used():
    resources = original_run_json(["gh", "api", "rate_limit"])["resources"]
    return resources["graphql"]["used"], resources["search"]["used"]


def main():
    config.use(config.load())
    scratch = Path(tempfile.mkdtemp())
    if board.STATE_PATH.exists():
        shutil.copy(board.STATE_PATH, scratch / "state.json")
    board.STATE_DIR, board.STATE_PATH = scratch, scratch / "state.json"
    fetch.run_json = board.run_json = timed_run_json

    graphql_before, search_before = rate_used()
    started = time.perf_counter()
    collect = board.collect()
    total = time.perf_counter() - started
    graphql_after, search_after = rate_used()
    shutil.rmtree(scratch)

    print(f"total {total:.2f}s | epics {len(collect['epics'])}, tickets {len(collect['by_key'])}, prs {len(collect['prs'])}")
    tools = {tool: sum(1 for name, *_ in calls if name.startswith(tool)) for tool in ("acli", "gh")}
    print(f"calls: acli {tools['acli']}, gh {tools['gh']} | rest searches {search_after - search_before}, "
          f"graphql points {graphql_after - graphql_before} (from gh api rate_limit; other gh use in the window adds to it)")
    print("\nstage                          calls  from    to   busiest")
    stages = {}
    for name, start, end in calls:
        stages.setdefault(name, []).append((start - started, end - started))
    for name, spans in sorted(stages.items(), key=lambda item: min(s for s, _ in item[1])):
        print(f"{name[:30]:30} {len(spans):5}  {min(s for s, _ in spans):5.2f} {max(e for _, e in spans):5.2f}  "
              f"{max(e - s for s, e in spans):5.2f}s")


if __name__ == "__main__":
    main()
