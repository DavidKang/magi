"""Jira adapter: epics and tickets through acli, built into entities."""

import datetime as dt

from . import process
from ..domain.entities import Epic, Ticket, TicketDetail
from ..domain.status import EPIC_STATUSES, column_for, ticket_order


def fetch_epics(settings):
    statuses = ", ".join(f'"{status}"' for status in EPIC_STATUSES)
    items = process.run_json(["acli", "jira", "workitem", "search", "--jql",
                            f"project = {settings.jira_project} AND issuetype = Epic AND status in ({statuses}) ORDER BY created DESC",
                            "--fields", "summary,status,assignee", "--limit", "100", "--json"])
    return [Epic(key=item["key"], summary=item["fields"]["summary"], status=item["fields"]["status"]["name"],
                 owner=(item["fields"].get("assignee") or {}).get("displayName", "Unassigned")) for item in items]


def fetch_children(epic_key):
    items = process.run_json(["acli", "jira", "workitem", "search", "--jql", f"parent = {epic_key} ORDER BY key",
                            "--limit", "500", "--json"])
    tickets = []
    for item in items:
        status = item["fields"]["status"]["name"]
        column = column_for(status)
        if column is None:
            continue
        assignee = item["fields"].get("assignee") or {}
        tickets.append(Ticket(key=item["key"], summary=item["fields"]["summary"], status=status, column=column,
                              assignee=assignee.get("displayName", "Unassigned")))
    return tickets


def fetch_updated(key):
    return process.run_json(["acli", "jira", "workitem", "view", key, "--fields", "updated", "--json"])["fields"]["updated"]


def changed_since(keys, minutes, linked_to=()):
    jql = " OR ".join([f"key in ({', '.join(keys)})"] + [f"issue in linkedIssues({key})" for key in linked_to])
    jql = f"({jql})" if linked_to else jql
    items = process.run_json(["acli", "jira", "workitem", "search", "--jql", f"{jql} AND updated >= -{minutes}m",
                            "--fields", "summary", "--paginate", "--json"])
    return {item["key"] for item in items}


def fetch_my_tickets(details):
    items = process.run_json(["acli", "jira", "workitem", "search", "--jql",
                            "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC",
                            "--limit", "100", "--json"])
    found = details([i["key"] for i in items])
    tickets = [Ticket(key=i["key"], summary=i["fields"]["summary"], status=i["fields"]["status"]["name"], detail=found[i["key"]])
               for i in items]
    return sorted(tickets, key=ticket_order)


def fetch_kanban(settings, details):
    """The tickets on the project's kanban board, in its rank: past the backlog and not done, epics aside."""
    items = process.run_json(["acli", "jira", "workitem", "search", "--jql",
                            f"project = {settings.jira_project} AND issuetype != Epic AND statusCategory != Done AND status != Backlog "
                            "ORDER BY Rank ASC", "--fields", "summary,status,assignee", "--limit", "100", "--json"])
    found = details([i["key"] for i in items])
    return [Ticket(key=i["key"], summary=i["fields"]["summary"], status=i["fields"]["status"]["name"],
                   assignee=(i["fields"].get("assignee") or {}).get("displayName", "Unassigned"), detail=found[i["key"]]) for i in items]


TICKET_FIELDS = "summary,status,description,creator,comment,parent,issuelinks,priority,labels,issuetype,created,updated"


def fetch_ticket_detail(key):
    return detail_from(view(key))


def fetch_ticket(key):
    fields = view(key)
    return Ticket(key=key, summary=fields["summary"], status=fields["status"]["name"], detail=detail_from(fields))


def view(key):
    return process.run_json(["acli", "jira", "workitem", "view", key, "--fields", TICKET_FIELDS, "--json"])["fields"]


def detail_from(fields):
    parent = fields.get("parent")
    return TicketDetail(
        type=fields["issuetype"]["name"], priority=(fields.get("priority") or {}).get("name"), labels=fields["labels"],
        creator=(fields["creator"] or {}).get("displayName", "unknown"), created=fields["created"], updated=fields["updated"],
        epic={"key": parent["key"], "summary": parent["fields"]["summary"]} if parent else None,
        links=[linked_ticket(link) for link in fields["issuelinks"]],
        description=adf_text(fields["description"]) if fields["description"] else "",
        comments=[{"id": c["id"], "author": (c.get("author") or {}).get("displayName", "unknown"), "created": c["created"],
                   "body": adf_text(c["body"])} for c in fields["comment"]["comments"]])


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
