"""Run the gh and acli processes the adapters read from."""

import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor


TOOLS = {"gh": "brew install gh, then gh auth login",
         "acli": "brew tap atlassian/homebrew-acli && brew install acli, then acli jira auth login"}


def missing_tools():
    return [f"{tool} not found. Install it with: {how}" for tool, how in TOOLS.items() if shutil.which(tool) is None]


def run_json(cmd):
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def parallel(fn, items):
    # Wide enough that one refresh's calls of a kind (epic children, PR searches) run in a single wave.
    with ThreadPoolExecutor(max_workers=16) as pool:
        return list(pool.map(fn, items))
