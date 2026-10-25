import asyncio
import base64
import datetime as dt
import json
from dataclasses import replace
import os
import re
import subprocess
import sys
import tempfile
import threading
import types
import time
from pathlib import Path

from textual.color import Color
from textual.content import Content
from textual.widgets import Input, OptionList, Static
import pytest
from PIL import Image as PILImage
from textual_image._geometry import CellSize
from textual_image.widget import Image, get_cell_size

from tarkon import board as board_module
from tarkon import config, fetch, github, jira, storage
from tarkon.html import page as web
from tarkon.tui import app as app_module
from tarkon.tui.app import TarkonApp
from tarkon.entities import Epic, FoundPr, PullRequest, Ticket, TicketDetail



@pytest.fixture(autouse=True, scope="session")
def madrid():
    os.environ["TZ"] = "Europe/Madrid"
    time.tzset()


@pytest.fixture(autouse=True)
def settings():
    config.use(config.Settings(**SETTINGS))
    yield
    config.use(None)


@pytest.fixture(autouse=True)
def default_theme():
    yield
    app_module.use_theme("default")


@pytest.fixture(autouse=True)
def aliases(monkeypatch):
    monkeypatch.setitem(board_module.TUI_REPO_ALIASES, "billing-reconciliation-service", "brs")

PR_ONE = PullRequest(url="https://github.com/acme/app/pull/1", repo="app", number=1, title="[ACME-1] First change",
                     author={"login": "alice"}, is_draft=False, review_decision="", reviews=[], review_requests=[{}],
                     created_at="2026-10-20T10:00:00Z", ci="failing", mergeable="CONFLICTING", head_ref_name="ACME-1-x",
                     commits=[{"committedDate": "2026-10-21T10:00:00Z"}], threads=[], conversation=[],
                     updated_at="2026-10-21T10:00:00Z", head_ref_oid="a1")
PR_TWO = PullRequest(url="https://github.com/acme/billing-reconciliation-service/pull/2", repo="billing-reconciliation-service",
                     number=2, title="[ACME-2] Second change", author={"login": "bob"}, is_draft=False, review_decision="APPROVED",
                     reviews=[{"submittedAt": "2026-10-22T09:00:00Z", "state": "APPROVED", "body": "", "author": {"login": "alice"}}],
                     review_requests=[], created_at="2026-10-21T10:00:00Z", ci="passing", mergeable="MERGEABLE", head_ref_name="ACME-2-y",
                     commits=[], threads=[], conversation=[], updated_at="2026-10-22T09:00:00Z", head_ref_oid="b2")
PR_THREE = replace(PR_ONE, url="https://github.com/acme/app/pull/3", number=3, title="[ACME-3] Third change",
                   created_at="2026-10-23T10:00:00Z", head_ref_oid="c3")
TICKETS = [Ticket(key="ACME-1", summary="Ticket one", status="En proceso", column="doing", assignee="Ana"),
           Ticket(key="ACME-2", summary="Ticket two", status="Finalizado", column="done", assignee="Ana")]
TICKET_DETAIL = TicketDetail(type="Story", priority="Low", labels=["blocked"], creator="Bob",
                             created="2026-10-08T16:12:45.341+0200", updated="2026-10-21T17:42:10.834+0200",
                             epic={"key": "ACME-100", "summary": "Epic one"},
                             links=[{"relation": "is blocked by", "key": "ACME-2", "summary": "Ticket two", "status": "En revisión"}],
                             description="Context\n\nUse the new reason column.",
                             comments=[{"id": "10", "author": "Carol", "created": "2026-10-20T10:00:00.000+0200", "body": "Looks good"}])
EPIC = Epic(key="ACME-100", summary="Epic one", status="Developing", owner="Ana")
SUBJECT = {"kind": "pr", "url": "https://github.com/acme/app/pull/1", "ref": "app#1", "title": "[ACME-1] First change"}


def board(prs):
    return {"epics": [EPIC], "tickets_by_epic": {"ACME-100": TICKETS}, "by_key": {t.key: t for t in TICKETS}, "prs": prs, "review_prs": [],
            "my_prs": [PR_ONE], "my_tickets": [Ticket(key="OPS-7", summary="Ticket seven", status="Tareas por hacer"),
                                             Ticket(key="ACME-1", summary="Ticket one", status="En proceso", detail=TICKET_DETAIL)],
            "attention": [{"subject": SUBJECT, "reason": "Open for review, but the ticket is still In progress. Move it to In review?"}],
            "changes": [{"at": "2026-10-24T02:04", "tone": "commented", "label": "New PR", "subject": SUBJECT, "note": None, "aside": None,
                         "item": PR_ONE.url}],
            "out": Path("board.html")}


SETTINGS = {"team": ["alice", "bob"], "jira_project": "ACME", "github_user": "alice", "github_org": "acme",
            "jira_url": "https://acme.atlassian.net"}

STATED = config.Settings(**SETTINGS)


def settings_file(cache, settings=SETTINGS):
    path = cache.with_name("config.json")
    path.write_text(json.dumps(settings))
    return path


def check(name, ok):
    assert ok, name


async def main(cache):
    boards = [board([PR_ONE, PR_TWO]), board([PR_ONE, PR_TWO, PR_THREE])]
    opened, copied, now = [], [], [1000.0]
    app = TarkonApp(load=lambda: boards.pop(0), opener=opened.append, copier=copied.append, clock=lambda: now[0], cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        detail = lambda: str(app.query_one("#detail", Static).render())
        title = lambda key: str(app.query_one(f"#panel-{key}").border_title)
        focused = lambda key: app.focused is app.query_one(f"#list-{key}")
        check("the tab bar shows Overview and Mine, Overview first", [tab.label.plain for tab in app.query("Tab")] == ["[1] Overview", "[2] Mine"]
              and app.query_one("Tabs").active == "tab-overview")
        check("the tab bar spans the whole width", app.query_one("Tabs").region.width == app.screen.region.width)
        check("details starts level with the first box", app.query_one("#detail").parent.region.y == app.query_one("#panel-attention").region.y)
        check("the header shows the logo instead of the rocket", isinstance(app.query_one("#top #logo"), Image)
              and "🚀" not in str(app.query_one("#top .brand").render()) and app.query_one("#top").outer_size.height == 1)
        logo, cell = app.query_one("#logo"), get_cell_size()
        width, height = PILImage.open(app_module.LOGO).size
        check("the title reads Tarkon", str(app.query_one("#top .brand").render()).strip() == "Tarkon")
        check("the boxes start one row below the header",
              app.query_one("#panel-attention").region.y >= app.query_one("#top").region.bottom + 1)
        check("the logo keeps its proportions", abs(logo.size.width - logo.size.height * cell.height * width / height / cell.width) <= 1)
        status = app.query_one("#status", Static)
        check("updated time uses the brand color", str(status.render()).startswith("updated")
              and status.styles.color == app.query_one(".brand").styles.color)
        check("there is no my desk or worktrees box", not app.query("#panel-desk") and not app.query("#panel-worktrees"))
        titles = [str(panel.border_title) for panel in app.query(".panel")]
        check("overview numbers its boxes next to details",
              titles == ["[3] attention 1", "[4] team prs 2", "[5] changes 1", "[6] epics 1", "[7] my prs 1", "[8] my tickets 2", "details"])
        check("overview starts on the attention box", "Move it to In review?" in detail())
        heights = {key: app.query_one(f"#panel-{key}").outer_size.height for key in ("attention", "prs", "changes", "epics")}
        check("attention box fits its items", heights["attention"] == 5)
        check("epics box fits its items", heights["epics"] == 5)
        check("team prs and changes share the rest", abs(heights["prs"] - heights["changes"]) <= 1 and heights["prs"] > 5)
        await pilot.click("#list-prs", offset=(2, 1))
        check("click in the team prs box shows that PR", "Second change" in detail())
        await pilot.click("#list-changes", offset=(2, 0))
        check("click in the changes box shows that change", "New PR" in detail())
        await pilot.press("enter")
        check("enter opens the item of the focused box", opened == [PR_ONE.url])
        opened.clear()
        await pilot.press("4")
        check("4 focuses the team prs box", focused("prs") and "Second change" in detail())
        await pilot.press("k")
        check("k moves up, detail keeps the ticket prefix", "[ACME-1] First change" in detail())
        await pilot.press("j")
        check("j moves to next PR", "Second change" in detail())
        bar = app.query_one("#list-epics", OptionList).get_option_at_index(0).prompt
        segments = [(bar.plain[s.start:s.end], str(s.style)) for s in bar.spans if bar.plain[s.start] in "█░"]
        check("epic progress is a block bar", "█" * 10 + "░" * 10 in bar.plain)
        check("done blocks are green and the rest dim", segments == [("█" * 10, "#56d364"), ("░" * 10, "#6e7a87")])
        check("long repo shown as alias", "brs#2" in str(app.query_one("#list-prs", OptionList).get_option_at_index(1).prompt))
        await pilot.press("enter")
        check("enter opens the PR", opened == [PR_TWO.url])
        await pilot.click("#list-prs", offset=(2, 0))
        check("click on a row selects it", "First change" in detail())
        await pilot.click("#detail", offset=(10, 2))
        check("click on a detail link opens it", opened[-1] == PR_ONE.url)
        await pilot.press("slash")
        check("slash focuses the filter of the focused box", app.focused is app.query_one("#filter-prs"))
        await pilot.press(*"second")
        check("filter narrows the list", app.query_one("#list-prs", OptionList).option_count == 1)
        await pilot.press("escape")
        check("escape clears the filter", app.query_one("#list-prs", OptionList).option_count == 2 and focused("prs"))
        await pilot.press("3")
        check("3 focuses the attention box", focused("attention") and "Move it to In review?" in detail())
        await pilot.press("6")
        check("6 focuses the epics box", focused("epics") and "Epic one" in detail())
        await pilot.press("5")
        check("5 focuses the changes box", focused("changes"))
        await pilot.press("6")
        await pilot.press("y")
        check("y copies the epic key", copied == ["ACME-100"])
        now[0] += 15
        await pilot.press("r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("refresh within 30 seconds is skipped", title("prs") == "[4] team prs 2")
        check("skipped refresh says when the next one is allowed", any("next refresh in 15s" in n.message for n in app._notifications))
        now[0] += 16
        await pilot.press("r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("refresh reloads the board", title("prs") == "[4] team prs 3")
        check("refresh keeps the focused box", focused("epics"))
        tabs = app.query_one("Tabs")
        await pilot.press("7")
        await pilot.pause()
        check("7 opens the mine tab on my open prs", tabs.active == "tab-mine" and focused("mine_prs") and "First change" in detail())
        await pilot.press("8")
        await pilot.pause()
        tickets = app.query_one("#list-mine_tickets", OptionList)
        prompts = [str(tickets.get_option_at_index(i).prompt) for i in range(tickets.option_count)]
        check("my tickets are grouped under their status", len(prompts) == 4 and prompts[0].startswith("── Todo (1)")
              and "OPS-7" in prompts[1] and prompts[2].startswith("── In Progress (1)") and "ACME-1" in prompts[3])
        check("8 focuses my tickets on the first ticket", focused("mine_tickets") and "Ticket seven" in detail())
        check("a ticket cached before the detail fetch shows no detail fields", "creator" not in detail() and "epic" not in detail())
        await pilot.press("c")
        await pilot.pause()
        check("c on a ticket with nothing to read says so", not isinstance(app.screen, app_module.ReviewScreen)
              and any("no review comments" in n.message for n in app._notifications))
        await pilot.press("slash", *"seven")
        await pilot.pause()
        prompts = [str(tickets.get_option_at_index(i).prompt) for i in range(tickets.option_count)]
        check("filtering my tickets drops the groups with no match", len(prompts) == 2 and prompts[0].startswith("── Todo (1)") and "OPS-7" in prompts[1])
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()
        check("2 on the mine tab keeps the focused box", tabs.active == "tab-mine" and focused("mine_tickets") and "Ticket seven" in detail())
        await pilot.press("j")
        check("j skips the status line to the next ticket, with its PRs", "Ticket one" in detail() and "app#1" in detail())
        check("my ticket detail names the status in English", "In Progress" in detail() and "En proceso" not in detail())
        await pilot.press("enter")
        check("enter opens the ticket in Jira", opened[-1] == "https://acme.atlassian.net/browse/ACME-1")
        check("my ticket detail shows type, priority, epic, creator, dates and labels",
              all(text in detail() for text in ["Story", "Low", "ACME-100", "Epic one", "creator", "Bob", "Oct 08", "updated", "blocked"]))
        check("my ticket detail shows its links with the other ticket's status",
              "is blocked by" in detail() and "ACME-2" in detail() and "In review" in detail())
        check("my ticket detail previews the description and counts the comments",
              "Use the new reason column." in detail() and "comments 1 · c to open" in detail())
        await pilot.press("c")
        await pilot.pause()
        popup = app.screen
        listing = popup.query_one(OptionList)
        prompts = [str(listing.get_option_at_index(i).prompt) for i in range(listing.option_count)]
        check("c opens the ticket's description and comments", isinstance(popup, app_module.ReviewScreen) and len(prompts) == 2
              and prompts[0].splitlines()[:2] == ["description", "Bob"] and prompts[1].splitlines() == ["comment", "Carol", "Looks good"])
        check("the ticket popup is titled with the key and summary", "ACME-1 · Ticket one" in str(popup.query_one("#review").border_title))
        check("the ticket popup shows the whole description", "Use the new reason column." in str(popup.query_one("#review-comments", Static).render()))
        await pilot.press("j", "enter")
        check("enter on a ticket comment opens that comment in Jira", opened[-1] == "https://acme.atlassian.net/browse/ACME-1?focusedCommentId=10")
        await pilot.press("escape")
        await pilot.press("1")
        await pilot.pause()
        check("1 goes back to the overview tab", tabs.active == "tab-overview" and focused("attention"))
        await pilot.press("2")
        await pilot.pause()
        check("2 opens the mine tab", tabs.active == "tab-mine" and focused("mine_prs"))
        await pilot.press("1")
        await pilot.pause()
        await pilot.click("#tab-mine")
        await pilot.pause()
        check("clicking the mine tab focuses my prs", tabs.active == "tab-mine" and focused("mine_prs"))


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


def test_ticket_detail_edges():
    ticket = Ticket(key="ACME-1", summary="Ticket one", status="En proceso", detail=replace(
        TICKET_DETAIL, epic=None, comments=[], description="\n".join(f"line {n}" for n in range(1, 15))))
    lines = Content.from_markup(app_module.ticket_entry(ticket, [], STATED).detail).plain.splitlines()
    check("a ticket without an epic shows a dash", "epic     —" in lines)
    check("a long description is cut with a hint to open it",
          "line 12" in lines and "line 13" not in lines and "… c to read it all" in lines)
    check("a ticket without comments shows no comments line", not any(line.startswith("comments") for line in lines))
    cached = app_module.ticket_entry(Ticket(key="OPS-7", summary="Ticket seven", status="Tareas por hacer"), [], STATED)
    check("a ticket cached before the detail fetch has nothing to open", cached.popup[1] == [])
    shuffled = {**board([]), "my_tickets": [Ticket(key="A-1", summary="a", status="En proceso"),
                                            Ticket(key="A-2", summary="b", status="Tareas por hacer"),
                                            Ticket(key="A-3", summary="c", status="En proceso")]}
    check("my tickets from an older cache are regrouped by status",
          [e.group for e in app_module.entries(shuffled, STATED)["mine_tickets"]] == ["Todo", "In Progress", "In Progress"])


def test_ticket_links():
    ticket = Ticket(key="ACME-1", summary="Ticket one", status="En proceso", detail=replace(
        TICKET_DETAIL, links=[*TICKET_DETAIL.links, {"relation": "relates to", "key": "ACME-3", "summary": "Third", "status": "Backlog"}]))
    lines = Content.from_markup(app_module.ticket_entry(ticket, [], STATED).detail).plain.splitlines()
    start = lines.index("── links ──")
    check("ticket links are a list, one item per link with its title below",
          lines[start + 1:start + 5] == ["• is blocked by ACME-2 (In review)", "  Ticket two", "• relates to ACME-3 (Backlog)", "  Third"]
          and not any(line.startswith("link ") for line in lines))


def test_adf_rendering():
    check("jira rich text reads as plain text", jira.adf_text(ADF) ==
          "Context\n\nUse `reason` only.\nAsk @Bob\n\n- one\n- two\n\na | b\n1 | 2\n\n    x = 1\n    y = 2")


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
    check("lists, quotes, cards, emoji, statuses, dates, media and panels read as plain text", jira.adf_text(ADF_MORE) ==
          "1. first\n  - nested\n2. second\n\n> quoted\n\n---\n\nhttps://example.com/a [link] :tada: DONE 2026-10-22\n\n[attachment]\n\nin a panel")


def ticket_view(key):
    return {"key": key, "fields": {
        "summary": "S", "issuetype": {"name": "Story"}, "priority": {"name": "Low"}, "labels": ["blocked"], "creator": {"displayName": "Bob"},
        "created": "2026-10-08T16:12:45.341+0200", "updated": "2026-10-21T17:42:10.834+0200",
        "parent": {"key": "ACME-100", "fields": {"summary": "Epic one"}},
        "issuelinks": [{"type": {"inward": "is blocked by", "outward": "blocks"},
                        "inwardIssue": {"key": "ACME-2", "fields": {"summary": "Ticket two", "status": {"name": "En revisión"}}}}],
        "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Context"}]},
                                                   {"type": "paragraph", "content": [{"type": "text", "text": "Use the new reason column."}]}]},
        "comment": {"comments": [{"id": "10", "author": {"displayName": "Carol"}, "created": "2026-10-20T10:00:00.000+0200",
                                  "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Looks good"}]}]}}]}}}


def test_my_tickets_fetch():
    items = [{"key": "ACME-6", "fields": {"summary": "Next", "status": {"name": "Tareas por hacer"}}},
             {"key": "ACME-5", "fields": {"summary": "Review me", "status": {"name": "En revisión"}}},
             {"key": "OPS-7", "fields": {"summary": "Odd status", "status": {"name": "Blocked"}}},
             {"key": "ACME-1", "fields": {"summary": "Doing", "status": {"name": "En proceso"}}},
             {"key": "ACME-3", "fields": {"summary": "Later", "status": {"name": "Backlog"}}},
             {"key": "ACME-4", "fields": {"summary": "Doing too", "status": {"name": "En proceso"}}}]
    seen, run_json = [], fetch.run_json
    fetch.run_json = lambda cmd: seen.append(cmd) or (items if cmd[3] == "search" else ticket_view(cmd[4]))
    try:
        tickets = jira.fetch_my_tickets(lambda keys: dict(zip(keys, fetch.parallel(jira.fetch_ticket_detail, keys))))
    finally:
        fetch.run_json = run_json
    check("my tickets are every assigned ticket not done, in one search",
          [cmd[3] for cmd in seen].count("search") == 1
          and "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC" in seen[0])
    check("each ticket's detail comes from one view", sorted(cmd[4] for cmd in seen if cmd[3] == "view") == sorted(i["key"] for i in items))
    check("my tickets come in board order, each status together, unknown statuses last, latest update first within a status",
          [t.key for t in tickets] == ["ACME-3", "ACME-6", "ACME-1", "ACME-4", "ACME-5", "OPS-7"])
    check("my tickets carry their detail", tickets[0] == Ticket(key="ACME-3", summary="Later", status="Backlog", detail=TICKET_DETAIL))


def test_sparse_ticket_detail():
    view = {"key": "OPS-9", "fields": {
        "summary": "S", "issuetype": {"name": "Task"}, "priority": None, "labels": [], "creator": None,
        "created": "2026-10-08T16:12:45.341+0200", "updated": "2026-10-21T17:42:10.834+0200", "parent": None, "issuelinks": [],
        "description": None, "comment": {"comments": [{"id": "11", "created": "2026-10-20T10:00:00.000+0200",
                                                       "body": {"type": "doc", "content": []}}]}}}
    run_json = fetch.run_json
    fetch.run_json = lambda cmd: view
    try:
        detail = jira.fetch_ticket_detail("OPS-9")
    finally:
        fetch.run_json = run_json
    check("a ticket with empty jira fields still loads", detail == TicketDetail(
        type="Task", priority=None, labels=[], creator="unknown", created="2026-10-08T16:12:45.341+0200",
        updated="2026-10-21T17:42:10.834+0200", epic=None, links=[], description="",
        comments=[{"id": "11", "author": "unknown", "created": "2026-10-20T10:00:00.000+0200", "body": ""}]))


def test_rows_view_model():
    from tarkon import rows
    from tarkon.html import page
    from tarkon.tui import app as tui_app
    config.use(None)
    ticket = TICKETS[0]
    row = rows.pr_row(PR_ONE, {ticket.key: ticket}, STATED)
    check("a pr row is plain data built from the settings passed in",
          row["ref"] == "app#1" and row["url"] == PR_ONE.url and row["author"] == "alice" and row["review"] == ("waiting", "Awaiting review")
          and row["ci"] == "failing" and row["conflict"] and row["review_requested"] and row["age"] == fetch.days_since(PR_ONE.created_at)
          and row["tickets"] == [{"key": "ACME-1", "url": "https://acme.atlassian.net/browse/ACME-1", "status": "En proceso",
                                  "summary": "Ticket one"}])
    linked = rows.ticket_row(ticket, [PR_ONE, PR_TWO], STATED)
    check("a ticket row is plain data with its linked prs",
          linked["key"] == "ACME-1" and linked["url"] == "https://acme.atlassian.net/browse/ACME-1" and linked["status"] == "In Progress"
          and [pr["ref"] for pr in linked["prs"]] == ["app#1"] and linked["prs"][0]["review"] == "Awaiting review")
    tui = Content.from_markup(tui_app.ticket_entry(ticket, [PR_ONE], STATED).detail).plain
    html = re.sub(r"<[^>]+>", "", page.tui_ticket(ticket, [PR_ONE], STATED)["detail"])
    check("the TUI and the html TUI design show the same row data", all("app#1 Awaiting review" in text for text in (tui, html)))
    check("the TUI styles live in a tcss file the app loads",
          Path(tui_app.__file__).with_name("app.tcss").exists() and tui_app.TarkonApp.CSS_PATH == "app.tcss"
          and not tui_app.TarkonApp.CSS)
    check("the html template is read from its package", Path(page.__file__).with_name("template.html").exists())


def test_html_mine():
    page = web.mine([], [], [Ticket(key="ACME-1", summary="Ticket one", status="En proceso")], STATED)
    check("html lists my open tickets with their status in English",
          "My open tickets" in page and "In Progress" in page and "En proceso" not in page and "in status" not in page)
    row = web.tui_ticket(Ticket(key="ACME-1", summary="Ticket one", status="En proceso"), [], STATED)["row"]
    check("the html tui mirror shows my ticket's status in English in three columns",
          "In Progress" in row and "En proceso" not in row and row.count("<span") == 3)


def test_status_labels():
    labels = {status: jira.status_label(status) for status in
              ["Tareas por hacer", "En proceso", "En revisión", "Finalizado", "Backlog", "Developing", "Blocked"]}
    check("Spanish statuses read in English, the rest as Jira names them", labels == {
        "Tareas por hacer": "Todo", "En proceso": "In Progress", "En revisión": "In review", "Finalizado": "Done",
        "Backlog": "Backlog", "Developing": "Developing", "Blocked": "Blocked"})


def failing_load():
    raise subprocess.CalledProcessError(1, ["gh", "search", "prs", "--json", "number"], stderr="API rate limit exceeded\n")


def unmapped_load():
    jira.column_for("Blocked")


async def unmapped_status(cache):
    app = TarkonApp(load=unmapped_load, opener=print, copier=print, cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        try:
            await asyncio.wait_for(app.workers.wait_for_complete(), 5)
        except TimeoutError:
            pass
        await pilot.pause()
        check("an unmapped jira status fails the refresh instead of leaving it running",
              not app.refreshing and any("Unmapped Jira status: Blocked" in n.message for n in app._notifications))


async def reopen(cache):
    calls = []
    def load():
        calls.append(1)
        return board([PR_ONE, PR_TWO, PR_THREE])
    storage.write(cache, {"at": 1000.0, "board": board([PR_ONE])})
    app = TarkonApp(load=load, opener=print, copier=print, clock=lambda: 1015.0, cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("reopening within 30 seconds does not refresh", calls == [])
        check("reopening within 30 seconds shows the saved board", str(app.query_one("#panel-prs").border_title) == "[4] team prs 1")
    app = TarkonApp(load=load, opener=print, copier=print, clock=lambda: 1090.0, cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("reopening after 30 seconds refreshes once", calls == [1])
        check("refreshed board replaces the saved one", str(app.query_one("#panel-prs").border_title) == "[4] team prs 3")
        check("successful refresh saves the board", storage.read(cache)["at"] == 1090.0)


async def stale_cache(cache):
    old = board([replace(PR_ONE, threads=[{**THREAD, "comments": [{**THREAD["comments"][0], "author": None}]}])])
    cache.write_text(json.dumps({"at": 1000.0, "board": old}, default=storage.encode))
    calls = []
    app = TarkonApp(load=lambda: calls.append(1) or board([PR_ONE]), opener=print, copier=print, clock=lambda: 1030.0, cache=cache,
                         config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("a cache from an older version is ignored and the board refreshes", calls == [1])


async def throttle_across_runs(cache):
    calls = []
    def load():
        calls.append(1)
        return board([PR_ONE])
    app = TarkonApp(load=failing_load, opener=print, copier=print, clock=lambda: 1000.0, cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
    app = TarkonApp(load=load, opener=print, copier=print, clock=lambda: 1015.0, cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("reopening within 30 seconds of a failed refresh does not refresh", calls == [])
        check("an empty board says when it will refresh", "next refresh in 15s" in str(app.query_one("#status", Static).render()))
        await pilot.press("r")
        await pilot.pause()
        check("r within 30 seconds of a refresh in an earlier run is skipped",
              calls == [] and any("next refresh in 15s" in n.message for n in app._notifications))
    app = TarkonApp(load=load, opener=print, copier=print, clock=lambda: 1031.0, cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("reopening after 30 seconds refreshes", calls == [1])


async def running(cache):
    release, calls = threading.Event(), []
    def slow_load():
        calls.append(1)
        release.wait(5)
        return board([PR_ONE])
    now = [1000.0]
    app = TarkonApp(load=slow_load, opener=print, copier=print, clock=lambda: now[0], cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        now[0] += 120
        await pilot.press("r")
        await pilot.pause()
        check("refresh while one is running is skipped", any("refresh already running" in n.message for n in app._notifications))
        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("only one load ran", len(calls) == 1)


async def failure(cache):
    app = TarkonApp(load=failing_load, opener=print, copier=print, cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("failed refresh keeps the app running", app.is_running)
        check("failed refresh shows the command error", any("API rate limit exceeded" in n.message for n in app._notifications))
        check("failed refresh saves nothing", not cache.exists())


async def first_run(cache):
    cache = cache.parent / "missing" / "cache.json"
    path, calls = cache.with_name("config.json"), []
    def load():
        calls.append(1)
        return board([PR_ONE])
    app = TarkonApp(load=load, opener=print, copier=print, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        check("the config panel shows the logo instead of the rocket", isinstance(app.screen.query_one("#logo"), Image)
              and all("🚀" not in str(brand.render()) for brand in app.screen.query(".brand")))
        inputs = {i.id.removeprefix("config-"): i for i in app.screen.query(Input)}
        check("first run opens the config panel with the five fields", sorted(inputs) == sorted(SETTINGS))
        check("config fields start empty with a placeholder", all(not i.value and i.placeholder for i in inputs.values()))
        check("board waits until the config is saved", calls == [])
        check("config panel hides the board keys on first run",
              not app.check_action("focus_filter", ()) and not app.check_action("refresh", ()) and not app.check_action("toggle_theme", ())
              and app.screen.check_action("save", ()))
        inputs["team"].value = "alice, bob"
        await pilot.click("#config-save")
        await pilot.pause()
        check("saving with empty fields is refused", not path.exists()
              and any("Fill in every field" in n.message for n in app._notifications))
        for key, value in {"jira_project": "ACME", "github_user": "alice", "github_org": "acme",
                           "jira_url": "https://acme.atlassian.net"}.items():
            inputs[key].value = value
        await pilot.pause(0.3)
        await pilot.click("#config-save")
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("saving writes the config", json.loads(path.read_text()) == {**SETTINGS, "theme": "default"})
        check("saving opens the board", calls == [1] and str(app.query_one("#panel-prs").border_title) == "[4] team prs 1")
        check("the TUI cache is written into a folder created on demand", cache.exists())


async def edit(cache):
    path = settings_file(cache)
    app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, cache=cache, config_path=path, edit_config=True)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        inputs = {i.id.removeprefix("config-"): i for i in app.screen.query(Input)}
        check("config command can be cancelled", app.screen.check_action("cancel", ()))
        check("config command shows the saved values", inputs["team"].value == "alice, bob" and inputs["jira_project"].value == "ACME")
        inputs["team"].value = "alice bob, carol"
        await pilot.click("#config-save")
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("config command saves the changes", json.loads(path.read_text())["team"] == ["alice", "bob", "carol"])
        check("config command then opens the board", str(app.query_one("#panel-prs").border_title) == "[4] team prs 1")


async def first_run_cancel(cache):
    path, calls = cache.with_name("config.json"), []
    app = TarkonApp(load=lambda: calls.append(1), opener=print, copier=print, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.click("#config-cancel")
        await pilot.pause()
        check("cancel on first run quits without saving or loading", not app.is_running and not path.exists() and calls == [])


async def edit_cancel(cache):
    path = settings_file(cache)
    app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, cache=cache, config_path=path, edit_config=True)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        app.screen.query_one("#config-team", Input).value = "zed"
        await pilot.click("#config-cancel")
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("cancel keeps the saved config", json.loads(path.read_text()) == {**SETTINGS, "theme": "default"})
        check("cancel goes to the board", str(app.query_one("#panel-prs").border_title) == "[4] team prs 1")


def test_quit_while_refreshing(cache):
    started, release, finished, loads = threading.Event(), threading.Event(), threading.Event(), []

    def load():
        loads.append(threading.current_thread())
        started.set()
        release.wait(10)
        finished.set()
        return board([PR_ONE])

    async def run():
        app = TarkonApp(load=load, opener=print, copier=print, cache=cache, config_path=settings_file(cache))
        async with app.run_test(size=(160, 40)) as pilot:
            await asyncio.to_thread(started.wait, 5)
            await pilot.press("q")
    asyncio.run(run())
    check("quitting does not wait for a running refresh", started.is_set() and not finished.is_set())
    errors, hook = [], threading.excepthook
    threading.excepthook = errors.append
    try:
        release.set()
        for thread in loads:
            thread.join(5)
    finally:
        threading.excepthook = hook
    check("a refresh that ends after quitting finishes quietly", finished.is_set() and errors == [])


QUIT_SCRIPT = """
import asyncio, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tarkon import fetch
from tarkon.tui import app as app_module

cache, done, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
started = threading.Event()


def item(_):
    started.set()
    time.sleep(0.5)
    with done.open("a") as out:
        out.write("x")


def load():
    if mode == "running":
        return fetch.parallel(item, range(40))
    if mode == "failed":
        pool = ThreadPoolExecutor(max_workers=8)
        for n in range(40):
            pool.submit(item, n)
        started.wait(5)
    raise RuntimeError("gh failed")


async def run():
    app = app_module.TarkonApp(load=load, opener=print, copier=print, cache=cache, config_path=cache.with_name("config.json"))
    async with app.run_test(size=(160, 40)) as pilot:
        if mode == "running":
            await asyncio.to_thread(started.wait, 5)
        else:
            await app.workers.wait_for_complete()
        await pilot.pause()
        if mode == "code":
            app.exit(return_code=3)
        else:
            await pilot.press("q")
    return app


app_module.leave(asyncio.run(run()))
"""


def quit_script(cache, mode):
    cache = cache.parent / mode / cache.name
    cache.parent.mkdir()
    settings_file(cache)
    done = cache.with_name("done")
    try:
        result = subprocess.run([sys.executable, "-c", QUIT_SCRIPT, str(cache), str(done), mode], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None, 40
    return result.returncode, len(done.read_text()) if done.exists() else 0


def test_quit_drops_queued_fetches(cache):
    code, finished = quit_script(cache, "running")
    check("quitting mid-refresh drops the fetches still queued", code == 0 and finished < 40)
    code, finished = quit_script(cache, "failed")
    check("quitting after a failed refresh drops the fetches it left queued", code == 0 and finished < 40)
    code, _ = quit_script(cache, "code")
    check("the app's exit code reaches the shell", code == 3)


def test_config_ignores_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({**SETTINGS, "theme": "lcars", "added_later": 1}))
    check("a config written by a newer version still loads", config.load(path) == config.Settings(**SETTINGS, theme="lcars"))


def test_settings_used():
    config.use(config.Settings(team=["alice"], jira_project="ACME", github_user="me", github_org="acme",
                               jira_url="https://acme.atlassian.net/"))
    check("jira links use the configured site", 'href="https://acme.atlassian.net/browse/ACME-9"' in web.jira_link("ACME-9", config.settings))
    seen, run_json = [], fetch.run_json
    items = [{"key": "ACME-9", "fields": {"summary": "Newer", "status": {"name": "Rollout"}, "assignee": None}},
             {"key": "ACME-2", "fields": {"summary": "Older", "status": {"name": "Developing"},
                                          "assignee": {"displayName": "Ana"}}}]
    fetch.run_json = lambda cmd: seen.append(cmd) or items
    try:
        epics = jira.fetch_epics(config.settings)
    finally:
        fetch.run_json = run_json
    jql = seen[0][seen[0].index("--jql") + 1]
    check("epics come from the configured project in Developing or Rollout, newest first",
          jql == 'project = ACME AND issuetype = Epic AND status in ("Developing", "Rollout") ORDER BY created DESC')
    check("fetched epics keep Jira's order", epics == [
        Epic(key="ACME-9", summary="Newer", status="Rollout", owner="Unassigned"),
        Epic(key="ACME-2", summary="Older", status="Developing", owner="Ana")])


def test_epic_changes():
    epic_one, epic_two = EPIC, replace(EPIC, key="ACME-200", summary="Epic two")
    one, two, three = (Ticket(key=key, summary=f"Ticket {key}", status="En proceso") for key in ("ACME-1", "ACME-2", "ACME-3"))
    summaries = {t.key: t.summary for t in (one, two, three)}
    pr = replace(PR_TWO, head_ref_oid="abc")
    before = board_module.snapshot([epic_one], {"ACME-100": [one]}, [], STATED)
    now = board_module.snapshot([epic_one, epic_two], {"ACME-100": [one], "ACME-200": [two, three]}, [pr], STATED)
    found = board_module.changes_between(before, now, summaries, {}, STATED)
    check("a new epic is one change with its summary", [(c["label"], c["item"]) for c in found]
          == [("New epic", "https://acme.atlassian.net/browse/ACME-200")] and found[0]["subject"]["title"] == "Epic two")
    check("an epic leaving needs no lookup of its PRs", board_module.vanished_prs(now, before) == [])
    found = board_module.changes_between(now, before, summaries, {}, STATED)
    check("an epic leaving is one change, without per-ticket changes",
          [(c["label"], c["item"]) for c in found] == [("Off the epics", "https://acme.atlassian.net/browse/ACME-200")])
    grown = board_module.snapshot([epic_one], {"ACME-100": [one, two]}, [], STATED)
    found = board_module.changes_between(before, grown, summaries, {}, STATED)
    check("a new ticket in a known epic still joins the epics", [c["label"] for c in found] == ["En proceso"]
          and found[0]["note"] == "joins the epics")
    legacy = {key: value for key, value in before.items() if key != "epics"}
    found = board_module.changes_between(legacy, grown, summaries, {}, STATED)
    check("a saved state without epics still reports new tickets", [c["label"] for c in found] == ["En proceso"])


def test_domain_returns_data():
    gone = replace(PR_ONE, url="https://github.com/acme/app/pull/8", number=8, title="[ACME-1] Gone", head_ref_oid="x")
    before = board_module.snapshot([], {}, [gone], STATED)
    now = board_module.snapshot([], {}, [], STATED)
    check("a vanished pr outside quiet epics needs its state", board_module.vanished_prs(before, now) == [gone.url])
    found = board_module.changes_between(before, now, {}, {gone.url: "MERGED"}, STATED)
    check("a vanished pr is labelled from the state it was given, as data", found == [
        {"item": gone.url, "tone": "approved", "label": "Merged", "note": None, "aside": None,
         "subject": {"kind": "pr", "url": gone.url, "ref": "app#8", "title": "[ACME-1] Gone"}}])
    tickets = [replace(TICKETS[0], prs=[PR_ONE])]
    check("attention items are data, never html", board_module.attention_items(tickets, [], {}, STATED) == [
        {"subject": SUBJECT, "reason": "Open for review, but the ticket is still In progress. Move it to In review?"}])


def test_pr_titles_read_like_their_links():
    for title, shown in (("[ACME-1]NoSpace", "[ACME-1] NoSpace"), ("[ACME-6]   multi   space", "[ACME-6] multi   space"),
                         ("[ACME-1][ACME-30] mixed", "[ACME-1] [ACME-30] mixed"), ("[ACME-4] ", "[ACME-4]"), ("No key", "No key")):
        check(f"a pr titled {title!r} reads {shown!r}", board_module.subject_text(board_module.pr_subject("u", "app#1", title)) == shown)


def test_vanished_prs_need_their_state():
    gone = replace(PR_ONE, head_ref_oid="x")
    with pytest.raises(KeyError):
        board_module.changes_between(board_module.snapshot([], {}, [gone], STATED), board_module.snapshot([], {}, [], STATED), {}, {}, STATED)


def test_tui_loads_the_board(monkeypatch):
    asked = []
    monkeypatch.setattr(board_module, "collect", lambda settings: asked.append(settings) or "board")
    app = TarkonApp()
    app.settings = STATED
    check("the TUI refresh collects the board with the app's settings, without writing the html page",
          app.load() == "board" and asked == [STATED])


def test_domain_reads_no_global_settings(monkeypatch):
    monkeypatch.setattr(config, "settings", None)
    pr = replace(PR_ONE, head_ref_oid="a1")
    found = board_module.changes_between(board_module.snapshot([], {}, [], STATED), board_module.snapshot([], {}, [pr], STATED), {}, {}, STATED)
    check("changes take the settings they are given", [c["label"] for c in found] == ["New PR"])
    check("pr ticket keys take the project they are given", board_module.ticket_keys_in(pr, "ACME") == {"ACME-1"})


def test_unmapped_status_raises():
    with pytest.raises(jira.UnmappedStatus, match="Unmapped Jira status: Blocked"):
        jira.column_for("Blocked")


def test_html_unmapped_status_exits_cleanly(monkeypatch):
    monkeypatch.setattr(config, "load", lambda: STATED)
    monkeypatch.setattr(web, "build", lambda: (_ for _ in ()).throw(jira.UnmappedStatus("Unmapped Jira status: Blocked")))
    with pytest.raises(SystemExit, match="Unmapped Jira status: Blocked"):
        web.main()


def test_days_since_reads_today(monkeypatch):
    class Day(dt.date):
        @classmethod
        def today(cls):
            return dt.date(2026, 1, 10)
    monkeypatch.setattr(fetch.dt, "date", Day)
    check("ages count from the day they are read, not from import", fetch.days_since("2026-01-08T10:00:00Z") == 2)


def test_storage(tmp_path):
    path = tmp_path / "nested" / "data.json"
    check("a missing file reads as nothing", storage.read(path) is None)
    storage.write(path, {"board": {"ñ": 1}})
    check("a written file reads back, in a folder created on demand", storage.read(path) == {"board": {"ñ": 1}})
    check("a full write leaves no temp file", sorted(p.name for p in path.parent.iterdir()) == ["data.json"])
    path.write_text('{"board": {}}')
    check("a file from before versioning reads as nothing", storage.read(path) is None)
    for version in (storage.VERSION - 1, storage.VERSION + 1):
        path.write_text(f'{{"version": {version}, "board": {{}}}}')
        check(f"a file from another version reads as nothing: {version}", storage.read(path) is None)
    path.write_text('{"version": ')
    check("a half-written file reads as nothing", storage.read(path) is None)
    for content in ("[]", "null", '"text"'):
        path.write_text(content)
        check(f"json that is not an object reads as nothing: {content}", storage.read(path) is None)
    path.write_bytes('{"name": "Mart'.encode()[:-1] + "í".encode()[:1])
    check("a file cut inside a utf-8 character reads as nothing", storage.read(path) is None)


def test_storage_crash(tmp_path, monkeypatch):
    path = tmp_path / "data.json"
    storage.write(path, {"kept": True})

    def crash(target, text, **options):
        target.open("w").close()
        raise OSError("disk full")
    monkeypatch.setattr(Path, "write_text", crash)
    try:
        storage.write(path, {"kept": False})
    except OSError:
        pass
    monkeypatch.undo()
    check("a write cut off midway keeps the previous file", storage.read(path) == {"kept": True})


def test_entities(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "run_json", lambda cmd: {"data": {"search": {"nodes": [light(PR_TWO)]}}})
    check("a pr search builds found prs", isinstance(github.search_prs("is:pr")[0], FoundPr))
    monkeypatch.setattr(fetch, "run_json", lambda cmd: {"data": {"pr0": pr_node(2, None)}})
    check("a pr fetch builds pull requests", isinstance(github.fetch_prs([("acme/app", 2)])[0], PullRequest))
    monkeypatch.setattr(fetch, "run_json", lambda cmd: [{"key": "ACME-9", "fields": {
        "summary": "S", "status": {"name": "Rollout"}, "assignee": None}}])
    check("epics are built from jira", isinstance(jira.fetch_epics(STATED)[0], Epic))
    check("an epic's children are tickets", isinstance(jira.fetch_children("ACME-9")[0], Ticket))
    monkeypatch.setattr(fetch, "run_json", lambda cmd: [{"key": "ACME-1", "fields": {"summary": "S", "status": {"name": "En proceso"}}}]
                        if cmd[3] == "search" else ticket_view(cmd[4]))
    mine = jira.fetch_my_tickets(lambda keys: {key: jira.fetch_ticket_detail(key) for key in keys})
    check("my tickets are tickets carrying their detail", isinstance(mine[0], Ticket) and isinstance(mine[0].detail, TicketDetail))
    path = tmp_path / "entities.json"
    storage.write(path, {"epic": Epic("ACME-1", "S", "Rollout", "Ana")})
    check("storage writes an entity as its fields", storage.read(path) == {"epic": {"key": "ACME-1", "summary": "S", "status": "Rollout", "owner": "Ana"}})
    path.write_text('{"version": 2, "board": {}}')
    check("files written before entities read as nothing", storage.read(path) is None)


def test_cached_board_reads_back(tmp_path):
    def shown(found):
        return {key: [(e.detail, e.url, e.search) for e in found_entries] for key, found_entries in app_module.entries(found, STATED).items()}
    found = board([PR_ONE, PR_TWO])
    storage.write(tmp_path / "cache.json", {"board": found})
    again = board_module.saved_board(storage.read(tmp_path / "cache.json")["board"])
    check("a cached board reads back as the same board", shown(again) == shown(found))


def test_state_write(tmp_path, monkeypatch):
    monkeypatch.setattr(board_module, "STATE_PATH", tmp_path / "state.json")
    board_module.save_state({"tickets": {}}, [])
    check("the state is saved through storage", storage.read(board_module.STATE_PATH) == {"snapshot": {"tickets": {}}, "changes": []})


def light(pr, updated="2026-10-24T10:00:00Z", ci="SUCCESS"):
    owner_repo = pr.url.split("/")[3] + "/" + pr.url.split("/")[4]
    return {"url": pr.url, "number": pr.number, "updatedAt": updated, "title": pr.title, "headRefName": pr.head_ref_name,
            "mergeable": pr.mergeable, "author": pr.author, "repository": {"nameWithOwner": owner_repo},
            "head": {"nodes": [{"commit": {"statusCheckRollup": {"state": ci} if ci else None}}]}}


def test_search_prs(monkeypatch):
    seen = []
    monkeypatch.setattr(fetch, "run_json", lambda cmd: seen.append(cmd) or {"data": {"search": {"nodes": [
        {**light(PR_TWO, ci="FAILURE"), "author": None}]}}})
    found = github.search_prs("is:pr is:open org:acme author:alice")
    query = next(arg for arg in seen[0] if arg.startswith("query="))
    check("pr searches go through graphql, not the rest search api",
          seen[0][:3] == ["gh", "api", "graphql"] and 'search(type: ISSUE, query: "is:pr is:open org:acme author:alice", first: 100)' in query)
    check("a search returns light prs with their ci, repo and update time", found == [FoundPr(
        url=PR_TWO.url, number=2, updated_at="2026-10-24T10:00:00Z", title=PR_TWO.title, head_ref_name="ACME-2-y",
        mergeable="MERGEABLE", author={"login": "ghost"}, name_with_owner="acme/billing-reconciliation-service",
        repo="billing-reconciliation-service", ci="failing")])
    check("the rest pr searches are gone", not any(hasattr(module, name) for module in (fetch, github) for name in
                                                    ("search_team_prs", "search_open_prs", "search_merged_prs", "search_review_requested_from_me")))


def test_changed_since(monkeypatch):
    seen = []
    monkeypatch.setattr(fetch, "run_json", lambda cmd: seen.append(cmd) or [{"key": "A-2", "fields": {"summary": "x"}}])
    check("jira says which tickets changed in the last minutes, by key", jira.changed_since(["A-1", "A-2"], 15) == {"A-2"}
          and "key in (A-1, A-2) AND updated >= -15m" in seen[0] and "--paginate" in seen[0])
    seen.clear()
    jira.changed_since(["A-1", "A-2"], 15, linked_to=["A-1"])
    check("tickets linked to the given ones are asked about too",
          "(key in (A-1, A-2) OR issue in linkedIssues(A-1)) AND updated >= -15m" in seen[0])
    monkeypatch.setattr(fetch, "run_json", lambda cmd: {"fields": {"updated": "2026-10-21T17:42:10.834+0200"}})
    check("a ticket's update time is returned, not written into it", jira.fetch_updated("A-1") == "2026-10-21T17:42:10.834+0200")


def test_refetch_changed(tmp_path, monkeypatch):
    path = tmp_path / "found.json"
    asked, changed = [], []
    monkeypatch.setattr(board_module, "changed_since", lambda keys, minutes, linked_to=(): changed.append((sorted(keys), minutes)) or {"A-2"})
    monkeypatch.setattr(board_module, "time", types.SimpleNamespace(time=lambda: 1600.0))

    def fetch_one(key):
        asked.append(key)
        return f"{key} #{len(asked)}"
    first = board_module.refetch_changed(path, ["A-1", "A-2"], fetch_one, 1000.0)
    check("a first refresh fetches every key", sorted(asked) == ["A-1", "A-2"] and changed == [])
    asked.clear()
    second = board_module.refetch_changed(path, ["A-1", "A-2", "A-3"], fetch_one, 1600.0)
    check("the next refresh asks jira what changed since the last one, with a margin", changed == [(["A-1", "A-2"], 15)])
    check("only changed or new keys are fetched again", sorted(asked) == ["A-2", "A-3"] and second["A-1"] == first["A-1"])
    board_module.refetch_changed(path, ["A-3"], fetch_one, 2000.0)
    check("keys that left the board leave the cache", sorted(storage.read(path)["found"]) == ["A-3"])
    changed.clear()
    monkeypatch.setattr(board_module, "time", types.SimpleNamespace(time=lambda: 2600.0))
    board_module.refetch_changed(path, ["A-3"], fetch_one, 2000.0)
    check("the window runs until jira is asked, not until the refresh started", changed == [(["A-3"], 15)]
          and storage.read(path)["at"] == 2000.0)


def test_refetch_changed_links(tmp_path, monkeypatch):
    path = tmp_path / "found.json"
    asked, linked = [], []
    monkeypatch.setattr(board_module, "time", types.SimpleNamespace(time=lambda: 1600.0))
    monkeypatch.setattr(board_module, "changed_since", lambda keys, minutes, linked_to=(): linked.append(sorted(linked_to)) or {"B-9"})

    def fetch_one(key):
        asked.append(key)
        return {"links": [{"key": "B-9"}] if key == "A-1" else []}
    links = lambda detail: [link["key"] for link in detail["links"]]
    board_module.refetch_changed(path, ["A-1", "A-2"], fetch_one, 1000.0, links)
    asked.clear()
    board_module.refetch_changed(path, ["A-1", "A-2"], fetch_one, 1600.0, links)
    check("jira is asked about the tickets linked to the cached ones", linked == [["A-1", "A-2"]])
    check("a ticket is fetched again when a ticket it links to changed", asked == ["A-1"])


def test_parallel_runs_one_wave():
    barrier = threading.Barrier(12, timeout=5)
    check("twelve calls run at once, in one wave", fetch.parallel(lambda i: barrier.wait() >= 0, range(12)) == [True] * 12)


def test_pr_states(monkeypatch):
    seen = []
    monkeypatch.setattr(fetch, "run_json", lambda cmd: seen.append(cmd) or {"data": {
        "pr0": {"pullRequest": {"state": "MERGED"}}, "pr1": {"pullRequest": {"state": "CLOSED"}}}})
    urls = ["https://github.com/acme/app/pull/8", "https://github.com/acme/web/pull/9"]
    states = github.fetch_pr_states(urls)
    query = next(arg for arg in seen[0] if arg.startswith("query="))
    check("vanished pr states come from one graphql call", len(seen) == 1 and states == {urls[0]: "MERGED", urls[1]: "CLOSED"}
          and 'name: "web"' in query and "pullRequest(number: 9)" in query)
    check("nothing vanished asks nothing", github.fetch_pr_states([]) == {} and len(seen) == 1)


def test_collect(tmp_path, monkeypatch):
    three = replace(PR_THREE, url="https://github.com/acme/renamed/pull/3")
    lights = {"team": [light(PR_TWO)], "review": [light(three), light(PR_ONE)], "open": [light(PR_ONE)]}
    details = {1: PR_ONE, 2: PR_TWO, 3: three}
    queries, asked = [], []

    def search(query):
        queries.append(query)
        kind = "team" if "author:" in query else "review" if "user-review-requested" in query else "merged" if "is:merged" in query else "open"
        return [github.light_pr(node) for node in lights.get(kind, [])]

    def details_of(items):
        items = list(items)
        asked.append(items)
        current = {n["number"]: n for kind in lights.values() for n in kind}
        return [replace(details[number], updated_at=current[number]["updatedAt"]) for _, number in items]
    asked_jira = []
    fakes = {"fetch_my_tickets": lambda details: [Ticket(key="ACME-9", summary="Ticket nine", status="En proceso",
                                                         detail=details(["ACME-9"])["ACME-9"])],
             "fetch_ticket_detail": lambda key: replace(TICKET_DETAIL, description=f"{key} detail", links=[{"key": "ACME-50"}]),
             "fetch_updated": lambda key: f"{key} updated",
             "changed_since": lambda keys, minutes, linked_to=(): asked_jira.append((sorted(keys), sorted(linked_to))) or set(),
             "search_prs": search, "fetch_prs": details_of,
             "fetch_epics": lambda settings: [EPIC],
             "fetch_children": lambda key: [replace(t, prs=[]) for t in TICKETS], "fetch_pr_states": lambda urls: {}}
    for name, fake in fakes.items():
        monkeypatch.setattr(board_module, name, fake)
    monkeypatch.setattr(board_module, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(board_module, "PR_CACHE_PATH", tmp_path / "prs.json")
    monkeypatch.setattr(board_module, "UPDATED_CACHE_PATH", tmp_path / "updated.json")
    monkeypatch.setattr(board_module, "MY_TICKETS_CACHE_PATH", tmp_path / "my-tickets.json")
    config.use(None)
    found = board_module.collect(STATED)
    check("the team's prs come from one search naming every author",
          "is:pr is:open archived:false org:acme author:alice author:bob" in queries)
    check("review requests and ticket keys are searched too", "is:pr is:open archived:false org:acme user-review-requested:@me" in queries
          and "is:pr is:open archived:false org:acme ACME-100 OR ACME-1" in queries and "is:pr is:merged org:acme ACME-1" in queries)
    check("every pr on the board is fetched once, in one go", len(asked) == 1
          and sorted(asked[0]) == [("acme/app", 1), ("acme/billing-reconciliation-service", 2), ("acme/renamed", 3)])
    check("review requests keep their order", [pr.number for pr in found["review_prs"]] == [3, 1])
    active = [t for t in found["by_key"].values() if t.column in board_module.ACTIVE_COLUMNS]
    check("active tickets take their update time from the update cache", active
          and all(t.updated == f"{t.key} updated" for t in active)
          and sorted(storage.read(tmp_path / "updated.json")["found"]) == sorted(t.key for t in active))
    check("my tickets take their details from their own cache", found["my_tickets"][0].detail.description == "ACME-9 detail"
          and list(storage.read(tmp_path / "my-tickets.json")["found"]) == ["ACME-9"])
    asked.clear()
    again = board_module.collect(STATED)
    check("the next refresh asks jira what changed, and about the tickets linked to mine",
          sorted(asked_jira) == sorted([(sorted(t.key for t in active), []), (["ACME-9"], ["ACME-9"])]))
    check("my ticket details read back from the cache are entities", isinstance(again["my_tickets"][0].detail, TicketDetail)
          and again["my_tickets"][0].detail.description == "ACME-9 detail")
    check("an unchanged pr is not fetched again", asked in ([], [[]]))
    lights["open"] = [light(PR_ONE, updated="2026-10-25T08:00:00Z")]
    lights["review"] = [light(three), light(PR_ONE, updated="2026-10-25T08:00:00Z")]
    lights["team"] = [light(PR_TWO, ci="FAILURE")]
    asked.clear()
    found = board_module.collect(STATED)
    check("only the pr updated since the last refresh is fetched again", asked == [[("acme/app", 1)]])
    check("ci comes from the search even when the detail is reused", {pr.number: pr.ci for pr in found["prs"]} == {1: "passing", 2: "failing"})


def test_refresh_policy():
    check("the board refreshes itself every 5 minutes", app_module.REFRESH_SECONDS == 5 * 60)


def test_data_paths():
    home = Path.home()
    check("state lives in ~/.local/state/tarkon", board_module.STATE_PATH == home / ".local/state/tarkon/state.json")
    check("the html page lives next to the state", web.OUT == home / ".local/state/tarkon/board.html")
    check("the TUI cache lives in ~/.cache/tarkon", app_module.CACHE == home / ".cache/tarkon/cache.json")
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "missing" / "board.html"
        found = {**board([PR_ONE]), "merged_by_ticket": {}, "now": {"prs": {}}}
        collect, path = web.collect, web.OUT
        web.collect, web.OUT = lambda settings: found, out
        try:
            result = web.build()
        finally:
            web.collect, web.OUT = collect, path
        check("the html page is written into a folder created on demand", out.exists() and result["out"] == out)
        page = out.read_text().lower()
        check("the html page has no worktrees or herdr", "worktree" not in page and "herdr" not in page)
    check("nothing scans ~/projects or calls herdr", not hasattr(fetch, "fetch_worktrees") and not hasattr(fetch, "herdr_workspaces"))


def test_missing_tools():
    for args in ([], ["html"]):
        try:
            result = subprocess.run([sys.executable, "-m", "tarkon", *args], capture_output=True, text=True,
                                    cwd=Path(__file__).parent, env={**os.environ, "PATH": "/usr/bin:/bin"}, timeout=15)
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess(args, None, "", "timed out")
        check(f"missing gh and acli are explained before {' '.join(args) or 'the TUI'} starts",
              result.returncode == 1 and "gh not found" in result.stderr and "brew install gh" in result.stderr
              and "acli not found" in result.stderr and "brew install acli" in result.stderr and "Traceback" not in result.stderr)


def test_escaping():
    check("tui links keep a title ending in a backslash",
          Content.from_markup(app_module.link("https://github.com/acme/app/pull/1", "Fix path\\")).plain.rstrip(app_module.ZERO_WIDTH_SPACE)
          == "Fix path\\")
    site = config.Settings(team=["alice"], jira_project="ACME", github_user="me", github_org="acme",
                           jira_url='https://acme.atlassian.net/"><b>site</b>')
    rendered = (web.jira_link("ACME-9<i>", site) + web.tui_epic(EPIC, TICKETS, site)["detail"]
                + web.tui_ticket(TICKETS[0], [], site)["detail"])
    check("jira links escape the site and the key", "<b>" not in rendered and "<i>" not in rendered)


HUNK = "@@ -1,5 +1,5 @@\n def total\n   items\n-    .sum(&:price)\n+    .sum { |item| item.price * item.qty }\n end"
THREAD = {"isResolved": False, "isOutdated": False, "path": "app/models/order.rb", "line": 12,
          "comments": [{"author": {"login": "carol"}, "body": "Rename qty to quantity", "createdAt": "2026-10-22T09:05:00Z", "diffHunk": HUNK,
                        "url": "https://github.com/acme/app/pull/2#discussion_r1"},
                       {"author": {"login": "bob"}, "body": "Done", "createdAt": "2026-10-22T10:00:00Z", "diffHunk": HUNK,
                        "url": "https://github.com/acme/app/pull/2#discussion_r2"}]}
OUTDATED = {"isResolved": False, "isOutdated": True, "path": "README.md", "line": None,
            "comments": [{"author": {"login": "alice"}, "body": "Typo", "createdAt": "2026-10-22T11:00:00Z",
                          "diffHunk": "@@ -1,2 +1,2 @@\n # App\n-Teh app", "url": "https://github.com/acme/app/pull/2#discussion_r3"}]}
NOTE = {"author": {"__typename": "User", "login": "alice"}, "body": "Nice work, this reads well", "createdAt": "2026-10-22T08:00:00Z",
        "url": "https://github.com/acme/app/pull/2#issuecomment-1"}
REPLY = {**NOTE, "author": {"__typename": "User", "login": "bob"}, "body": "Thanks!", "createdAt": "2026-10-22T09:30:00Z",
         "url": "https://github.com/acme/app/pull/2#issuecomment-2"}
CHANGES = {"submittedAt": "2026-10-22T09:00:00Z", "state": "CHANGES_REQUESTED", "body": "Please split this", "author": {"login": "carol"}}


def test_stardate():
    check("a stardate is the year, the day of the year and the tenth of the day", app_module.stardate(dt.datetime(2026, 10, 25, 12, 0)) == "26298.5")


def test_pr_rows():
    row = lambda pr: app_module.cell_row(app_module.pr_entry(pr, {}, STATED), app_module.PR_WIDTHS).plain
    check("team pr row shows the title's ticket code and the author", "[ACME-1]" in row(PR_ONE) and "alice" in row(PR_ONE))
    check("team pr row without a ticket code shows no code", "[" not in row(replace(PR_ONE, title="No ticket"))
          and "alice" in row(replace(PR_ONE, title="No ticket")))


def test_pr_comments():
    review = {"submittedAt": "2026-10-22T09:00:00Z", "state": "CHANGES_REQUESTED", "body": "Please split this", "author": {"login": "carol"}}
    pr = replace(PR_TWO, reviews=[*PR_TWO.reviews, review], commits=[{"committedDate": "2026-10-23T08:00:00Z"}], threads=[THREAD])
    detail = Content.from_markup(app_module.pr_entry(pr, {}, STATED).detail).plain
    check("pr detail counts the comments and says how to open them", "comments 2 · c to open" in detail)
    check("pr detail leaves the comments themselves to the popup", all(text not in detail for text in
          ("Please split this", "app/models/order.rb", ".sum { |item|", "Rename qty to quantity")))
    activity = detail[detail.index("── activity ──"):]
    check("activity is newest first", activity.index("commit") < activity.index("approved"))
    check("pr detail without comments has no comments line", "comments" not in Content.from_markup(app_module.pr_entry(PR_ONE, {}, STATED).detail).plain)


def test_conversation_comments():
    pr = replace(PR_TWO, reviews=[CHANGES], threads=[THREAD], conversation=[NOTE, REPLY])
    items = app_module.review_items(pr)
    check("conversation comments sit with the reviews by date, before the code threads",
          [str(item["row"]).splitlines()[0] for item in items] == ["comment", "changes requested", "comment", "order.rb:12"])
    check("a conversation comment shows its author and text", str(items[0]["row"]).splitlines()[1:] == ["alice", "Nice work, this reads well"]
          and "alice commented" in Content.from_markup(items[0]["place"]).plain
          and "Nice work, this reads well" in Content.from_markup("\n".join(items[0]["comments"])).plain)
    check("enter on a conversation comment opens that comment", items[0]["url"] == NOTE["url"])
    check("the detail counts conversation comments too",
          "comments 4 · c to open" in Content.from_markup(app_module.pr_entry(pr, {}, STATED).detail).plain)


def test_diff_rendering():
    diff = app_module.diff_text(HUNK, "app/models/order.rb")
    lines = diff.plain.splitlines()
    check("diff keeps the hunk header", lines[0].strip() == "@@ -1,5 +1,5 @@")
    check("diff numbers context lines on both sides", re.match(r"\s*1\s+1\s+def total", lines[1]) is not None)
    check("diff numbers a removed line on the old side", re.match(r"\s*3\s+-\s+\.sum\(&:price\)", lines[3]) is not None)
    check("diff numbers an added line on the new side", re.match(r"\s*3\s+\+\s+\.sum \{", lines[4]) is not None)
    check("the line numbers take only the width they need", lines[1].startswith("1 1  def total")
          and lines[4].startswith("  3 +    .sum {") and lines[0] == "    @@ -1,5 +1,5 @@")
    added_only = app_module.diff_text("@@ -0,0 +1,2 @@\n+first\n+second", "notes.md").plain.splitlines()
    check("a hunk of only additions shows a single number column", [line.rstrip() for line in added_only[1:]] == ["1 +first", "2 +second"]
          and added_only[0] == "  @@ -0,0 +1,2 @@")
    added = diff.plain.index("+    .sum {")
    check("added lines have a green background, removed ones red",
          any(span.start <= added < span.end and str(span.style).endswith(f"on {app_module.DIFF_BACKGROUNDS['+']}") for span in diff.spans)
          and app_module.DIFF_BACKGROUNDS["+"] != app_module.DIFF_BACKGROUNDS["-"])


async def review_popup(cache):
    pr_two = replace(PR_TWO, reviews=[*PR_TWO.reviews, CHANGES], threads=[THREAD, OUTDATED])
    opened, copied = [], []
    app = TarkonApp(load=lambda: board([PR_ONE, pr_two]), opener=opened.append, copier=copied.append, clock=lambda: 1000.0,
                         cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = lambda selector: str(app.screen.query_one(selector, Static).render())
        await pilot.press("4", "j", "c")
        check("c opens the review comments of the selected PR", isinstance(app.screen, app_module.ReviewScreen))
        check("the review popup blocks the theme key", not app.check_action("toggle_theme", ()))
        check("the popup lists the review and every open thread", app.screen.query_one(OptionList).option_count == 3)
        check("the popup title names the PR", "brs#2" in str(app.screen.query_one("#review").border_title))
        prompts = [str(app.screen.query_one(OptionList).get_option_at_index(i).prompt) for i in range(3)]
        check("each thread in the list previews its first comment", "Please split this" in prompts[0]
              and "Rename qty to quantity" in prompts[1] and "Typo" in prompts[2])
        check("each thread shows file, author and description on their own lines",
              prompts[1].splitlines() == ["order.rb:12", "carol · 2 comments", "Rename qty to quantity"]
              and prompts[0].splitlines() == ["changes requested", "carol", "Please split this"])
        check("an outdated thread says so in the list", prompts[2].splitlines()[0] == "README.md · outdated")
        check("the popup footer explains how to move", any(b.key_display == "j/k" for b in app.screen.query_one(OptionList)._bindings
                                                                                       .key_to_bindings.get("j", [])))
        check("a review shows its body without a diff", "Please split this" in text("#review-comments")
              and not app.screen.query_one("#review-diff-box").display)
        await pilot.press("j")
        check("j moves to the next thread and shows its file and line", "app/models/order.rb:12" in text("#review-place"))
        check("the thread shows its diff", app.screen.query_one("#review-diff-box").display and ".sum { |item|" in text("#review-diff"))
        check("the thread shows every comment in order", text("#review-comments").index("Rename qty") < text("#review-comments").index("Done"))
        await pilot.press("enter")
        check("enter opens the thread on GitHub", opened[-1] == THREAD["comments"][0]["url"])
        await pilot.press("y")
        check("y copies the thread link", copied[-1] == THREAD["comments"][0]["url"])
        await pilot.press("j")
        check("an outdated thread says so", "outdated" in text("#review-place") and "README.md" in text("#review-place"))
        await pilot.press("q")
        check("q closes the popup without quitting", not isinstance(app.screen, app_module.ReviewScreen) and app.is_running)
        await pilot.press("k", "c")
        check("c on a PR without comments keeps the board", not isinstance(app.screen, app_module.ReviewScreen))
        await pilot.press("j")
        detail = str(app.query_one("#detail", Static).render()).splitlines()
        row = next(i for i, line in enumerate(detail) if "c to open" in line)
        await pilot.click("#detail", offset=(10, row))
        check("clicking the comments line in the detail opens the popup", isinstance(app.screen, app_module.ReviewScreen))
        await pilot.press("escape")
        check("escape closes the popup", not isinstance(app.screen, app_module.ReviewScreen))


def pr_node(number, rollup):
    resolved = {**THREAD, "isResolved": True, "path": "app/old.rb"}
    bots = [{**NOTE, "author": {"__typename": "Bot", "login": "github-actions"}}, {**NOTE, "author": {"__typename": "User", "login": "deploybot"}}]
    return {"pullRequest": {
        "number": number, "title": "x", "url": f"https://github.com/acme/app/pull/{number}", "author": {"login": "alice"},
        "updatedAt": "2026-10-22T10:00:00Z", "headRefName": "x", "headRefOid": "h", "isDraft": False, "createdAt": "2026-10-20T10:00:00Z",
        "reviewDecision": None, "mergeable": "MERGEABLE",
        "reviewRequests": {"nodes": [{"requestedReviewer": {"__typename": "User"}}]}, "reviews": {"nodes": [CHANGES]},
        "commits": {"nodes": [{"commit": {"committedDate": "2026-10-21T10:00:00Z"}}, {"commit": {"committedDate": "2026-10-22T10:00:00Z"}}]},
        "head": {"nodes": [{"commit": {"statusCheckRollup": rollup}}]},
        "reviewThreads": {"nodes": [{**t, "comments": {"nodes": t["comments"]}} for t in (THREAD, resolved)]},
        "comments": {"nodes": [*bots, NOTE]}}}


def test_pr_fetch():
    rollups = [{"state": "FAILURE"}, {"state": "PENDING"}, {"state": "SUCCESS"}, None]
    seen, run_json = [], fetch.run_json

    def graph(cmd):
        seen.append(cmd)
        query = next(arg for arg in cmd if arg.startswith("query="))
        numbers = [int(n) for n in re.findall(r"pullRequest\(number: (\d+)\)", query)]
        return {"data": {f"pr{i}": pr_node(n, rollups[n % 4]) for i, n in enumerate(numbers)}}

    fetch.run_json = graph
    try:
        prs = github.fetch_prs([("acme/app", 2), ("acme/app", 3)])
        many = github.fetch_prs([("acme/app", n) for n in range(25)])
    finally:
        fetch.run_json = run_json
    query = next(arg for arg in seen[0] if arg.startswith("query="))
    check("prs come from one graphql call per batch of 3", len(seen) == 10 and all("graphql" in cmd for cmd in seen) and len(many) == 25)
    check("pr fetch asks for each pr by repo and number", 'owner: "acme"' in query and 'name: "app"' in query
          and "pullRequest(number: 2)" in query and "pullRequest(number: 3)" in query)
    check("pr fetch keeps the order it was asked", [pr.number for pr in many] == list(range(25)))
    check("pr fetch keeps only unresolved review threads", prs[0].threads == [THREAD])
    check("pr fetch keeps conversation comments from people, not bots", prs[0].conversation == [NOTE])
    check("pr fetch flattens reviews, review requests and commits", prs[0].reviews == [CHANGES] and len(prs[0].review_requests) == 1
          and [c["committedDate"] for c in prs[0].commits] == ["2026-10-21T10:00:00Z", "2026-10-22T10:00:00Z"])
    check("pr ci comes from the last commit's check rollup", [pr.ci for pr in many[:4]] == ["failing", "running", "passing", "none"])
    check("pr fetch names the repo", prs[0].repo == "app")
    check("pr fetch asks for the check rollup of the head commit only",
          "commits(last: 100) { nodes { commit { committedDate } } }" in query
          and "head: commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }" in query)
    node = pr_node(5, None)["pullRequest"]
    ghost = {**node, "author": None, "reviews": {"nodes": [{**CHANGES, "author": None}]},
             "reviewThreads": {"nodes": [{**THREAD, "comments": {"nodes": [{**THREAD["comments"][0], "author": None}]}}]}}
    pr = github.pr_from_graph(ghost, "acme/app")
    check("a deleted account reads as ghost", pr.author == {"login": "ghost"} and pr.reviews[0]["author"] == {"login": "ghost"}
          and pr.threads[0]["comments"][0]["author"] == {"login": "ghost"})
    check("pr fetch asks for every comment field the popup shows",
          all(re.search(rf"\b{name}\b", query) for name in ("login", "body", "createdAt", "diffHunk", "url")))


def test_logo_fit():
    source = PILImage.open(app_module.LOGO)
    for cell in (CellSize(8, 17), CellSize(10, 20), CellSize(9, 21)):
        image, columns = app_module.logo_image(2, cell)
        box = columns * cell.width / (2 * cell.height)
        check(f"logo fills a whole {columns}x2 box of {cell.width}x{cell.height} cells without stretching",
              abs(image.width / image.height - box) < 0.02 and image.height == source.height and image.width >= source.width)


def test_html_logo():
    with tempfile.TemporaryDirectory() as scratch:
        found = {**board([PR_ONE]), "merged_by_ticket": {}, "now": {"prs": {}}}
        collect, path = web.collect, web.OUT
        web.collect, web.OUT = lambda settings: found, Path(scratch) / "board.html"
        try:
            page = web.build()["out"].read_text()
        finally:
            web.collect, web.OUT = collect, path
    logo = "data:image/png;base64," + base64.b64encode((Path(web.__file__).parent.parent / "logo.png").read_bytes()).decode()
    check("html favicon is the logo", f'<link rel="icon" type="image/png" href="{logo}">' in page)
    check("html headers show the logo instead of the rocket", page.count(f'src="{logo}"') == 2 and "rotate(45 16 16)" not in page)


def test_html_lcars_design():
    template = Path(web.__file__).with_name("template.html").read_text()
    check("both design switches offer LCARS", template.count('<button type="button" data-design="lcars"') == 2)
    check("the page remembers the LCARS design", re.search(r'getItem\("tarkon-design"\).*"lcars"', template.splitlines()[4]) is not None)
    check("the LCARS design has its own look", ':root[data-design="lcars"] .masthead' in template)


def test_html_without_config():
    with tempfile.TemporaryDirectory() as home:
        result = subprocess.run([sys.executable, "-m", "tarkon", "html"], capture_output=True, text=True,
                                cwd=Path(__file__).parent, env={**os.environ, "HOME": home})
    check("html without config asks to configure first",
          result.returncode == 1 and "Run `python -m tarkon config` first" in result.stderr)


async def lcars_theme(cache):
    path = settings_file(cache)
    lcars = app_module.THEMES["lcars"]
    app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, clock=lambda: 1000.0, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("a config without a theme starts with the default one", app.screen.styles.background == Color.parse(app_module.THEMES["default"]["bg"]))
        check("the default theme has no LCARS frame", not any(app.query_one(f"#{name}").display for name in ("elbow", "bar", "sidebar")))
        await pilot.press("t")
        await pilot.pause()
        check("LCARS frames the header with an elbow", app.query_one("#elbow").display and app.query_one("#bar").display
              and str(app.query_one("#top .brand").render()) == "TARKON"
              and str(app.query_one("#status").render()).startswith("STARDATE "))
        check("LCARS titles panels with a two-digit code in capitals", str(app.query_one("#panel-prs").border_title) == "04-TEAM PRS 1"
              and str(app.query_one("#detail").parent.border_title) == "DETAILS")
        check("LCARS shows review and CI states as pills",
              "◖AWAITING REVIEW" in app.query_one("#list-prs").get_option_at_index(0).prompt.plain)
        buttons = list(app.query(".side"))
        check("LCARS adds a sidebar button per box, lit for the focused one", app.query_one("#sidebar").display
              and [str(b.render()).split() [0] for b in buttons] == ["03", "04", "05", "06", "07", "08"]
              and [b.has_class("-on") for b in buttons] == [True, False, False, False, False, False])
        await pilot.click("#side-changes")
        await pilot.pause()
        check("a sidebar button focuses its box", app.current_section == "changes" and app.query_one("#side-changes").has_class("-on"))
        check("t switches the TUI to LCARS", app.screen.styles.background == Color.parse(lcars["bg"])
              and app.query_one("#panel-prs").styles.border_top == ("panel", Color.parse(lcars["line"])))
        check("the switch repaints the board", lcars["accent"] in app.sections["prs"][0].detail)
        check("the theme is saved in the config", json.loads(path.read_text()) == {**SETTINGS, "theme": "lcars"})
    app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, clock=lambda: 1000.0, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("the saved theme applies on start", app.screen.styles.background == Color.parse(lcars["bg"]))
        await pilot.press("t")
        await pilot.pause()
        check("t switches back to the default theme", app.screen.styles.background == Color.parse(app_module.THEMES["default"]["bg"])
              and json.loads(path.read_text())["theme"] == "default")
        check("the default theme keeps its titles, states and header", str(app.query_one("#panel-prs").border_title) == "[4] team prs 1"
              and "awaiting review" in app.query_one("#list-prs").get_option_at_index(0).prompt.plain
              and str(app.query_one("#top .brand").render()) == "Tarkon"
              and not app.query_one("#sidebar").display)
    app = TarkonApp(load=failing_load, opener=print, copier=print, clock=lambda: 5000.0, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        check("switching the theme keeps a failed refresh visible", "refresh failed" in str(app.query_one("#status").render()))


async def lcars_edit(cache):
    path = settings_file(cache, {**SETTINGS, "theme": "lcars"})
    app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, cache=cache, config_path=path, edit_config=True)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        app.screen.query_one("#config-team", Input).value = "alice bob, carol"
        await pilot.click("#config-save")
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("editing the config keeps the saved theme", json.loads(path.read_text())["theme"] == "lcars")


@pytest.fixture
def cache(tmp_path):
    return tmp_path / "cache.json"


@pytest.mark.parametrize("scenario", [main, reopen, throttle_across_runs, running, failure, unmapped_status, first_run, first_run_cancel,
                                      edit, edit_cancel, review_popup, stale_cache, lcars_theme, lcars_edit], ids=lambda scenario: scenario.__name__)
def test_tui(scenario, cache):
    asyncio.run(scenario(cache))
