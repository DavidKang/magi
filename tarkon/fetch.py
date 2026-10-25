"""Fetch the board's raw data from Jira (acli) and GitHub (gh)."""

import datetime as dt
import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor


COLUMNS = [
    ("todo", "To do", {"Backlog", "Tareas por hacer"}),
    ("doing", "In progress", {"En proceso", "Developing", "Paused"}),
    ("review", "In review", {"En revisión"}),
    ("deploy", "Deploy", {"Ready To Deploy", "Rollout"}),
    ("done", "Done", {"Finalizado"}),
]
DISCARDED = {"Rejected / Cancelled"}
STATUS_RANK = {status: i for i, (_, _, statuses) in enumerate(COLUMNS) for status in statuses}
STATUS_LABELS = {"Tareas por hacer": "Todo", "En proceso": "In Progress", "En revisión": "In review", "Finalizado": "Done"}
EPIC_STATUSES = ["Developing", "Rollout"]

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


def search_terms(keys):
    chunks = [keys[start:start + 6] for start in range(0, len(keys), 6)]
    return [[token for key in chunk for token in ("OR", key)][1:] for chunk in chunks]


class UnmappedStatus(Exception):
    pass


def column_for(status):
    for key, _, statuses in COLUMNS:
        if status in statuses:
            return key
    if status in DISCARDED:
        return None
    raise UnmappedStatus(f"Unmapped Jira status: {status}")


def status_label(status):
    return STATUS_LABELS.get(status, status)


def days_since(iso):
    return (dt.date.today() - dt.date.fromisoformat(iso[:10])).days


def fetch_epics(settings):
    statuses = ", ".join(f'"{status}"' for status in EPIC_STATUSES)
    items = run_json(["acli", "jira", "workitem", "search", "--jql",
                      f"project = {settings.jira_project} AND issuetype = Epic AND status in ({statuses}) ORDER BY created DESC",
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


def fetch_updated(key):
    return run_json(["acli", "jira", "workitem", "view", key, "--fields", "updated", "--json"])["fields"]["updated"]


def changed_since(keys, minutes, linked_to=()):
    jql = " OR ".join([f"key in ({', '.join(keys)})"] + [f"issue in linkedIssues({key})" for key in linked_to])
    jql = f"({jql})" if linked_to else jql
    items = run_json(["acli", "jira", "workitem", "search", "--jql", f"{jql} AND updated >= -{minutes}m",
                      "--fields", "summary", "--paginate", "--json"])
    return {item["key"] for item in items}


def graphql(query):
    return run_json(["gh", "api", "graphql", "-f", f"query=query {{ {query} }}"])["data"]


def repository(owner_repo, number, fields):
    owner, name = owner_repo.split("/")
    return f'repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ pullRequest(number: {int(number)}) {{ {fields} }} }}'


def fetch_pr_states(urls):
    if not urls:
        return {}
    places = [url.split("/") for url in urls]
    data = graphql(" ".join(f"pr{i}: " + repository(f"{place[3]}/{place[4]}", place[6], "state") for i, place in enumerate(places)))
    return {url: data[f"pr{i}"]["pullRequest"]["state"] for i, url in enumerate(urls)}


def fetch_my_tickets(details):
    items = run_json(["acli", "jira", "workitem", "search", "--jql",
                      "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC",
                      "--limit", "100", "--json"])
    tickets = [{"key": i["key"], "summary": i["fields"]["summary"], "status": i["fields"]["status"]["name"]} for i in items]
    found = details([t["key"] for t in tickets])
    for ticket in tickets:
        ticket.update(found[ticket["key"]])
    return sorted(tickets, key=ticket_order)


def ticket_order(ticket):
    return STATUS_RANK.get(ticket["status"], len(COLUMNS)), ticket["status"]


TICKET_FIELDS = "summary,status,description,creator,comment,parent,issuelinks,priority,labels,issuetype,created,updated"


def fetch_ticket_detail(key):
    fields = run_json(["acli", "jira", "workitem", "view", key, "--fields", TICKET_FIELDS, "--json"])["fields"]
    parent = fields.get("parent")
    return {"type": fields["issuetype"]["name"], "priority": (fields.get("priority") or {}).get("name"), "labels": fields["labels"],
            "creator": (fields["creator"] or {}).get("displayName", "unknown"), "created": fields["created"], "updated": fields["updated"],
            "epic": {"key": parent["key"], "summary": parent["fields"]["summary"]} if parent else None,
            "links": [linked_ticket(link) for link in fields["issuelinks"]],
            "description": adf_text(fields["description"]) if fields["description"] else "",
            "comments": [{"id": c["id"], "author": (c.get("author") or {}).get("displayName", "unknown"), "created": c["created"], "body": adf_text(c["body"])}
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
    if kind == "date":
        return dt.datetime.fromtimestamp(int(node["attrs"]["timestamp"]) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
    if kind in {"mention", "emoji", "status"}:
        return node["attrs"].get("text") or node["attrs"].get("shortName", "")
    if kind == "inlineCard":
        return node["attrs"].get("url", "[link]")
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


HEAD_CI = "head: commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }"
LIGHT_FIELDS = f"url number updatedAt title headRefName mergeable author {{ login }} repository {{ nameWithOwner }} {HEAD_CI}"
PR_FIELDS = f"""number title url updatedAt headRefName headRefOid isDraft createdAt reviewDecision mergeable author {{ login }}
  reviewRequests(first: 20) {{ nodes {{ requestedReviewer {{ __typename }} }} }}
  reviews(first: 100) {{ nodes {{ author {{ login }} body state submittedAt }} }}
  commits(last: 100) {{ nodes {{ commit {{ committedDate }} }} }}
  {HEAD_CI}
  reviewThreads(first: 100) {{ nodes {{ isResolved isOutdated path line
    comments(first: 50) {{ nodes {{ author {{ login }} body createdAt diffHunk url }} }} }} }}
  comments(first: 100) {{ nodes {{ author {{ __typename login }} body createdAt url }} }}"""
# Small batches in parallel: GitHub resolves the aliases of one query roughly in sequence.
PRS_PER_QUERY = 3
GHOST = {"login": "ghost"}
CI_STATES = {"SUCCESS": "passing", "FAILURE": "failing", "ERROR": "failing", "PENDING": "running", "EXPECTED": "running"}


def fetch_prs(candidates):
    candidates = list(candidates)
    batches = [candidates[start:start + PRS_PER_QUERY] for start in range(0, len(candidates), PRS_PER_QUERY)]
    return [pr for batch in parallel(fetch_pr_batch, batches) for pr in batch]


def fetch_pr_batch(batch):
    data = graphql(" ".join(f"pr{i}: " + repository(repo, number, PR_FIELDS) for i, (repo, number) in enumerate(batch)))
    return [pr_from_graph(data[f"pr{i}"]["pullRequest"], repo) for i, (repo, _) in enumerate(batch)]


def search_prs(query):
    data = graphql(f"search(type: ISSUE, query: {json.dumps(query)}, first: 100) {{ nodes {{ ... on PullRequest {{ {LIGHT_FIELDS} }} }} }}")
    return [light_pr(node) for node in data["search"]["nodes"]]


def light_pr(node):
    light = {key: value for key, value in node.items() if key not in ("head", "repository")}
    owner_repo = node["repository"]["nameWithOwner"]
    return {**light, "author": node["author"] or GHOST, "nameWithOwner": owner_repo, "repo": owner_repo.split("/")[1], "ci": head_ci(node)}


def head_ci(node):
    head = node["head"]["nodes"]
    rollup = head[0]["commit"]["statusCheckRollup"] if head else None
    return CI_STATES[rollup["state"]] if rollup else "none"


def pr_from_graph(pr, repo):
    ci = head_ci(pr)
    pr = {key: value for key, value in pr.items() if key != "head"}
    return {**pr, "repo": repo.split("/")[1], "ci": ci, "author": pr["author"] or GHOST,
            "reviewRequests": pr["reviewRequests"]["nodes"], "reviews": with_authors(pr["reviews"]["nodes"]),
            "commits": [node["commit"] for node in pr["commits"]["nodes"]],
            "threads": [{**thread, "comments": with_authors(thread["comments"]["nodes"])} for thread in pr["reviewThreads"]["nodes"]
                        if not thread["isResolved"]],
            "conversation": [comment for comment in pr["comments"]["nodes"] if comment["author"] and not is_bot(comment["author"])]}


def with_authors(nodes):
    # GraphQL gives a deleted account a null author.
    return [{**node, "author": node["author"] or GHOST} for node in nodes]


def is_bot(author):
    return author["__typename"] == "Bot" or author["login"].lower().endswith("bot")


