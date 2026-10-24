"""Fetch the board's raw data from Jira (acli) and GitHub (gh)."""

import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from . import config

COLUMNS = [
    ("todo", "To do", {"Backlog", "Tareas por hacer"}),
    ("doing", "In progress", {"En proceso", "Developing", "Paused"}),
    ("review", "In review", {"En revisión"}),
    ("deploy", "Deploy", {"Ready To Deploy", "Rollout"}),
    ("done", "Done", {"Finalizado"}),
]
DISCARDED = {"Rejected / Cancelled"}
EPIC_STATUSES = ["Developing", "Rollout"]
TODAY = dt.date.today()

TOOLS = {"gh": "brew install gh, then gh auth login",
         "acli": "brew tap atlassian/homebrew-acli && brew install acli, then acli jira auth login"}


def missing_tools():
    return [f"{tool} not found. Install it with: {how}" for tool, how in TOOLS.items() if shutil.which(tool) is None]


def run_json(cmd):
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def parallel(fn, items):
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(fn, items))


def search_terms(keys):
    chunks = [keys[start:start + 6] for start in range(0, len(keys), 6)]
    return [[token for key in chunk for token in ("OR", key)][1:] for chunk in chunks]


def column_for(status):
    for key, _, statuses in COLUMNS:
        if status in statuses:
            return key
    if status in DISCARDED:
        return None
    sys.exit(f"Unmapped Jira status: {status}")


def days_since(iso):
    return (TODAY - dt.date.fromisoformat(iso[:10])).days


def fetch_epics():
    statuses = ", ".join(f'"{status}"' for status in EPIC_STATUSES)
    items = run_json(["acli", "jira", "workitem", "search", "--jql",
                      f"project = {config.settings.jira_project} AND issuetype = Epic AND status in ({statuses}) ORDER BY created DESC",
                      "--fields", "summary,status,assignee", "--limit", "100", "--json"])
    return [{"key": item["key"], "summary": item["fields"]["summary"], "status": item["fields"]["status"]["name"],
             "owner": (item["fields"].get("assignee") or {}).get("displayName", "Unassigned")} for item in items]


def fetch_children(epic_key):
    items = run_json(["acli", "jira", "workitem", "search", "--jql", f"parent = {epic_key} ORDER BY key",
                      "--limit", "500", "--json"])
    tickets = []
    for item in items:
        status = item["fields"]["status"]["name"]
        column = column_for(status)
        if column is None:
            continue
        assignee = item["fields"].get("assignee") or {}
        tickets.append({
            "key": item["key"],
            "summary": item["fields"]["summary"],
            "status": status,
            "column": column,
            "assignee": assignee.get("displayName", "Unassigned"),
            "updated": None,
            "prs": [],
        })
    return tickets


def fetch_updated(ticket):
    fields = run_json(["acli", "jira", "workitem", "view", ticket["key"], "--fields", "updated", "--json"])["fields"]
    ticket["updated"] = fields["updated"]


def search_open_prs(keys):
    found = {}
    for results in parallel(lambda terms: run_json(["gh", "search", "prs", *terms, "--owner", config.settings.github_org, "--state", "open",
                                                    "--archived=false", "--json", "number,repository,url", "--limit", "100"]),
                            search_terms(keys)):
        for pr in results:
            found[pr["url"]] = (pr["repository"]["nameWithOwner"], pr["number"])
    return found


def search_merged_prs(keys):
    return [pr for results in parallel(lambda terms: run_json(["gh", "search", "prs", *terms, "--owner", config.settings.github_org, "--merged",
                                                              "--json", "number,repository,url,title", "--limit", "100"]),
                                       search_terms(keys))
            for pr in results]


def search_review_requested_from_me():
    results = run_json(["gh", "search", "prs", "user-review-requested:@me", "--owner", config.settings.github_org, "--state", "open",
                        "--archived=false", "--json", "number,repository,url", "--limit", "100"])
    return {pr["url"]: (pr["repository"]["nameWithOwner"], pr["number"]) for pr in results}


def fetch_my_tickets():
    items = run_json(["acli", "jira", "workitem", "search", "--jql",
                      'assignee = currentUser() AND statusCategory = "In Progress" ORDER BY updated DESC',
                      "--limit", "100", "--json"])
    tickets = [{"key": i["key"], "summary": i["fields"]["summary"], "status": i["fields"]["status"]["name"]} for i in items]
    for t, days in zip(tickets, parallel(days_in_status, [t["key"] for t in tickets])):
        t["days_in_status"] = days
    return tickets


def status_changed_since(key, days_ago):
    return bool(run_json(["acli", "jira", "workitem", "search", "--jql",
                          f"key = {key} AND status CHANGED AFTER startOfDay(-{days_ago})", "--limit", "1", "--json"]))


def days_in_status(key):
    entered_category = run_json(["acli", "jira", "workitem", "view", key, "--fields", "statuscategorychangedate",
                                 "--json"])["fields"]["statuscategorychangedate"]
    low, high = 0, days_since(entered_category)
    while low < high:
        mid = (low + high) // 2
        if status_changed_since(key, mid):
            high = mid
        else:
            low = mid + 1
    return low


def search_team_prs():
    found = {}
    for results in parallel(lambda author: run_json(["gh", "search", "prs", "--author", author, "--owner", config.settings.github_org,
                                                     "--state", "open", "--archived=false",
                                                     "--json", "number,repository,url", "--limit", "100"]),
                            config.settings.team):
        for pr in results:
            found[pr["url"]] = (pr["repository"]["nameWithOwner"], pr["number"])
    return found


DISCUSSION_QUERY = """query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) {
    reviewThreads(first: 100) { nodes { isResolved isOutdated path line
      comments(first: 50) { nodes { author { login } body createdAt diffHunk url } } } }
    comments(first: 100) { nodes { author { __typename login } body createdAt url } } } } }"""


def fetch_pr(repo, number):
    with ThreadPoolExecutor(max_workers=2) as pool:
        ci = pool.submit(fetch_ci, repo, number)
        discussion = pool.submit(fetch_discussion, repo, number)
        pr = run_json(["gh", "pr", "view", str(number), "--repo", repo, "--json",
                       "number,title,url,headRefName,headRefOid,author,isDraft,createdAt,reviewDecision,reviewRequests,reviews,mergeable,commits"])
        pr["ci"] = ci.result()
        pr["threads"], pr["conversation"] = discussion.result()
    pr["repo"] = repo.split("/")[1]
    return pr


def is_bot(author):
    return author["__typename"] == "Bot" or author["login"].lower().endswith("bot")


def fetch_discussion(repo, number):
    owner, name = repo.split("/")
    data = run_json(["gh", "api", "graphql", "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"number={number}",
                     "-f", f"query={DISCUSSION_QUERY}"])
    pr = data["data"]["repository"]["pullRequest"]
    threads = [{**thread, "comments": thread["comments"]["nodes"]} for thread in pr["reviewThreads"]["nodes"] if not thread["isResolved"]]
    return threads, [comment for comment in pr["comments"]["nodes"] if comment["author"] and not is_bot(comment["author"])]


def fetch_ci(repo, number):
    result = subprocess.run(["gh", "pr", "checks", str(number), "--repo", repo, "--json", "bucket"],
                            capture_output=True, text=True)
    if "no checks reported" in result.stderr:
        return "none"
    buckets = {check["bucket"] for check in json.loads(result.stdout)}
    if "fail" in buckets:
        return "failing"
    if "pending" in buckets:
        return "running"
    return "passing"


