import types

from builders import TICKET_DETAIL, ticket_view
from magi import config
from magi.adapters import jira, process
from magi.domain.entities import Epic, Ticket, TicketDetail


ADF = {"type": "doc", "content": [
    {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Context"}]},
    {"type": "paragraph", "content": [{"type": "text", "text": "Use "}, {"type": "text", "text": "reason", "marks": [{"type": "code"}]},
                                      {"type": "text", "text": " only."}, {"type": "hardBreak"}, {"type": "text", "text": "Ask "},
                                      {"type": "mention", "attrs": {"text": "@Bob"}}]},
    {"type": "bulletList", "content": [{"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "one"}]}]},
                                       {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "two"}]}]}]},
    {"type": "table", "content": [
        {"type": "tableRow", "content": [{"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "a"}]}]},
                                         {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "b"}]}]}]},
        {"type": "tableRow", "content": [{"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "1"}]}]},
                                         {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "2"}]}]}]}]},
    {"type": "codeBlock", "content": [{"type": "text", "text": "x = 1\ny = 2"}]}]}


def test_adf_rendering():
    assert (jira.adf_text(ADF) ==
            "Context\n\nUse `reason` only.\nAsk @Bob\n\n- one\n- two\n\na | b\n1 | 2\n\n    x = 1\n    y = 2"), "jira rich text reads as plain text"


ADF_MORE = {"type": "doc", "content": [
    {"type": "orderedList", "content": [
        {"type": "listItem", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "first"}]},
            {"type": "bulletList", "content": [{"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "nested"}]}]}]}]},
        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "second"}]}]}]},
    {"type": "blockquote", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "quoted"}]}]},
    {"type": "rule"},
    {"type": "paragraph", "content": [
        {"type": "inlineCard", "attrs": {"url": "https://example.com/a"}}, {"type": "text", "text": " "},
        {"type": "inlineCard", "attrs": {"data": {"name": "Card"}}}, {"type": "text", "text": " "},
        {"type": "emoji", "attrs": {"shortName": ":tada:"}}, {"type": "text", "text": " "},
        {"type": "status", "attrs": {"text": "DONE"}}, {"type": "text", "text": " "},
        {"type": "date", "attrs": {"timestamp": "1792627200000"}}]},
    {"type": "mediaSingle", "content": [{"type": "media", "attrs": {}}]},
    {"type": "panel", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "in a panel"}]}]}]}


def test_adf_more_nodes():
    assert (jira.adf_text(ADF_MORE) ==
            "1. first\n  - nested\n2. second\n\n> quoted\n\n---\n\nhttps://example.com/a [link] :tada: DONE 2026-10-22\n\n[attachment]\n\nin a panel"), \
        "lists, quotes, cards, emoji, statuses, dates, media and panels read as plain text"


def test_my_tickets_fetch():
    items = [{"key": "ACME-6", "fields": {"summary": "Next", "status": {"name": "Tareas por hacer"}}},
             {"key": "ACME-5", "fields": {"summary": "Review me", "status": {"name": "En revisión"}}},
             {"key": "OPS-7", "fields": {"summary": "Odd status", "status": {"name": "Blocked"}}},
             {"key": "ACME-1", "fields": {"summary": "Doing", "status": {"name": "En proceso"}}},
             {"key": "ACME-3", "fields": {"summary": "Later", "status": {"name": "Backlog"}}},
             {"key": "ACME-4", "fields": {"summary": "Doing too", "status": {"name": "En proceso"}}}]
    seen, run_json = [], process.run_json
    process.run_json = lambda cmd: seen.append(cmd) or (items if cmd[3] == "search" else ticket_view(cmd[4]))
    try:
        tickets = jira.fetch_my_tickets(lambda keys: dict(zip(keys, process.parallel(jira.fetch_ticket_detail, keys))))
    finally:
        process.run_json = run_json
    assert [cmd[3] for cmd in seen].count("search") == 1, "my tickets are every assigned ticket not done, in one search"
    assert "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC" in seen[0], \
        "my tickets are every assigned ticket not done, in one search"
    assert sorted(cmd[4] for cmd in seen if cmd[3] == "view") == sorted(i["key"] for i in items), "each ticket's detail comes from one view"
    assert [t.key for t in tickets] == ["ACME-3", "ACME-6", "ACME-1", "ACME-4", "ACME-5", "OPS-7"], \
        "my tickets come in board order, each status together, unknown statuses last, latest update first within a status"
    assert tickets[0] == Ticket(key="ACME-3", summary="Later", status="Backlog", detail=TICKET_DETAIL), "my tickets carry their detail"


def test_kanban_fetch():
    items = [{"key": "ACME-6", "fields": {"summary": "Next", "status": {"name": "Tareas por hacer"}, "assignee": None}},
             {"key": "ACME-5", "fields": {"summary": "Review me", "status": {"name": "En revisión"}, "assignee": {"displayName": "Ana"}}}]
    seen, run_json = [], process.run_json
    process.run_json = lambda cmd: seen.append(cmd) or (items if cmd[3] == "search" else ticket_view(cmd[4]))
    try:
        tickets = jira.fetch_kanban(types.SimpleNamespace(jira_project="ACME"),
                                    lambda keys: dict(zip(keys, process.parallel(jira.fetch_ticket_detail, keys))))
    finally:
        process.run_json = run_json
    assert [cmd[3] for cmd in seen].count("search") == 1, "the kanban board's tickets come from one search"
    assert "project = ACME AND issuetype != Epic AND statusCategory != Done AND status != Backlog ORDER BY Rank ASC" in seen[0], \
        "the kanban board holds the project's tickets past the backlog and not done, epics aside, in the board's rank"
    assert [t.key for t in tickets] == ["ACME-6", "ACME-5"], "the kanban board's tickets keep the board's rank"
    assert tickets[1] == Ticket(key="ACME-5", summary="Review me", status="En revisión", assignee="Ana", detail=TICKET_DETAIL), \
        "a kanban ticket carries its assignee and its detail"
    assert tickets[0].assignee == "Unassigned", "a kanban ticket nobody has reads as unassigned"


def test_fetch_ticket():
    view = ticket_view("ACME-9")
    view["fields"]["status"] = {"name": "En revisión"}
    run_json = process.run_json
    process.run_json = lambda cmd: view
    try:
        ticket, detail = jira.fetch_ticket("ACME-9"), jira.fetch_ticket_detail("ACME-9")
    finally:
        process.run_json = run_json
    assert ticket == Ticket(key="ACME-9", summary="S", status="En revisión", detail=detail), \
        "a ticket fetched on its own carries its summary, status and detail"


def test_sparse_ticket_detail():
    view = {"key": "OPS-9", "fields": {
        "summary": "S", "issuetype": {"name": "Task"}, "priority": None, "labels": [], "creator": None,
        "created": "2026-10-08T16:12:45.341+0200", "updated": "2026-10-21T17:42:10.834+0200", "parent": None, "issuelinks": [],
        "description": None, "comment": {"comments": [{"id": "11", "created": "2026-10-20T10:00:00.000+0200",
                                                       "body": {"type": "doc", "content": []}}]}}}
    run_json = process.run_json
    process.run_json = lambda cmd: view
    try:
        detail = jira.fetch_ticket_detail("OPS-9")
    finally:
        process.run_json = run_json
    assert (detail == TicketDetail(
          type="Task", priority=None, labels=[], creator="unknown", created="2026-10-08T16:12:45.341+0200",
          updated="2026-10-21T17:42:10.834+0200", epic=None, links=[], description="",
          comments=[{"id": "11", "author": "unknown", "created": "2026-10-20T10:00:00.000+0200", "body": ""}])), \
        "a ticket with empty jira fields still loads"


def test_settings_used():
    site = config.Settings(team=["alice"], jira_project="ACME", github_user="me", github_org="acme", jira_url="https://acme.atlassian.net/")
    seen, run_json = [], process.run_json
    items = [{"key": "ACME-9", "fields": {"summary": "Newer", "status": {"name": "Rollout"}, "assignee": None}},
             {"key": "ACME-2", "fields": {"summary": "Older", "status": {"name": "Developing"},
                                          "assignee": {"displayName": "Ana"}}}]
    process.run_json = lambda cmd: seen.append(cmd) or items
    try:
        epics = jira.fetch_epics(site)
    finally:
        process.run_json = run_json
    jql = seen[0][seen[0].index("--jql") + 1]
    assert jql == 'project = ACME AND issuetype = Epic AND status in ("Developing", "Rollout") ORDER BY created DESC', \
        "epics come from the configured project in Developing or Rollout, newest first"
    assert (epics == [
          Epic(key="ACME-9", summary="Newer", status="Rollout", owner="Unassigned"),
          Epic(key="ACME-2", summary="Older", status="Developing", owner="Ana")]), "fetched epics keep Jira's order"


def test_changed_since(monkeypatch):
    seen = []
    monkeypatch.setattr(process, "run_json", lambda cmd: seen.append(cmd) or [{"key": "A-2", "fields": {"summary": "x"}}])
    assert jira.changed_since(["A-1", "A-2"], 15) == {"A-2"}, "jira says which tickets changed in the last minutes, by key"
    assert "key in (A-1, A-2) AND updated >= -15m" in seen[0], "jira says which tickets changed in the last minutes, by key"
    assert "--paginate" in seen[0], "jira says which tickets changed in the last minutes, by key"
    seen.clear()
    jira.changed_since(["A-1", "A-2"], 15, linked_to=["A-1"])
    assert "(key in (A-1, A-2) OR issue in linkedIssues(A-1)) AND updated >= -15m" in seen[0], "tickets linked to the given ones are asked about too"
    monkeypatch.setattr(process, "run_json", lambda cmd: {"fields": {"updated": "2026-10-21T17:42:10.834+0200"}})
    assert jira.fetch_updated("A-1") == "2026-10-21T17:42:10.834+0200", "a ticket's update time is returned, not written into it"
