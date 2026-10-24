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
STATUS_LABELS = {"Tareas por hacer": "Todo", "En proceso": "In Progress", "En revisión": "In review", "Finalizado": "Done"}
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


def status_label(status):
    return STATUS_LABELS.get(status, status)


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
                      "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC",
                      "--limit", "100", "--json"])
    order = {status: i for i, (_, _, statuses) in enumerate(COLUMNS) for status in statuses}
    tickets = [{"key": i["key"], "summary": i["fields"]["summary"], "status": i["fields"]["status"]["name"]} for i in items]
    for ticket, detail in zip(tickets, parallel(fetch_ticket_detail, [t["key"] for t in tickets])):
        ticket.update(detail)
    return sorted(tickets, key=lambda t: (order.get(t["status"], len(COLUMNS)), t["status"]))


TICKET_FIELDS = "summary,status,description,creator,comment,parent,issuelinks,priority,labels,issuetype,created,updated"


def fetch_ticket_detail(key):
    fields = run_json(["acli", "jira", "workitem", "view", key, "--fields", TICKET_FIELDS, "--json"])["fields"]
    parent = fields.get("parent")
    return {"type": fields["issuetype"]["name"], "priority": (fields.get("priority") or {}).get("name"), "labels": fields["labels"],
            "creator": fields["creator"]["displayName"], "created": fields["created"], "updated": fields["updated"],
            "epic": {"key": parent["key"], "summary": parent["fields"]["summary"]} if parent else None,
            "links": [linked_ticket(link) for link in fields["issuelinks"]],
            "description": adf_text(fields["description"]) if fields["description"] else "",
            "comments": [{"id": c["id"], "author": c["author"]["displayName"], "created": c["created"], "body": adf_text(c["body"])}
                         for c in fields["comment"]["comments"]]}


def linked_ticket(link):
    other = link.get("outwardIssue") or link["inwardIssue"]
    return {"relation": link["type"]["outward" if "outwardIssue" in link else "inward"], "key": other["key"],
            "summary": other["fields"]["summary"], "status": other["fields"]["status"]["name"]}


def adf_text(node):
    kind, children = node.get("type"), node.get("content", [])
    if kind == "text":
        return f'`{node["text"]}`' if any(mark["type"] == "code" for mark in node.get("marks", [])) else node["text"]
    if kind == "hardBreak":
        return "\n"
    if kind in {"mention", "emoji", "status", "date"}:
        return node["attrs"].get("text") or node["attrs"].get("shortName", "")
    if kind == "inlineCard":
        return node["attrs"]["url"]
    if kind in {"media", "mediaSingle", "mediaGroup"}:
        return "[attachment]"
    if kind == "rule":
        return "---"
    if kind in {"bulletList", "orderedList"}:
        return "\n".join(("- " if kind == "bulletList" else f"{n}. ") + adf_text(item) for n, item in enumerate(children, 1))
    if kind == "listItem":
        return "\n  ".join("\n".join(adf_text(child) for child in children).splitlines())
    if kind == "codeBlock":
        return "\n".join(f"    {line}" for line in "".join(adf_text(child) for child in children).splitlines())
    if kind == "blockquote":
        return "\n".join(f"> {line}" for line in "\n\n".join(adf_text(child) for child in children).splitlines())
    if kind == "table":
        return "\n".join(adf_text(row) for row in children)
    if kind == "tableRow":
        return " | ".join(adf_text(cell) for cell in children)
    if kind in {"tableCell", "tableHeader"}:
        return " ".join(adf_text(child) for child in children)
    if kind in {"paragraph", "heading"}:
        return "".join(adf_text(child) for child in children)
    return "\n\n".join(adf_text(child) for child in children)


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


