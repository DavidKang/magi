import datetime as dt
from dataclasses import replace

from textual.content import Content

from builders import CHANGES, EPIC, NOTE, PR_ONE, PR_TWO, REPLY, STATED, THREAD, TICKETS, TICKET_DETAIL, board
from tarkon import config
from tarkon.domain.entities import Ticket
from tarkon.html import page as web
from tarkon.tui import entries


def test_ticket_detail_edges():
    ticket = Ticket(key="ACME-1", summary="Ticket one", status="En proceso", detail=replace(
        TICKET_DETAIL, epic=None, comments=[], description="\n".join(f"line {n}" for n in range(1, 15))))
    lines = Content.from_markup(entries.ticket_entry(ticket, [], STATED).detail).plain.splitlines()
    assert "epic     —" in lines, "a ticket without an epic shows a dash"
    assert "line 12" in lines, "a long description is cut with a hint to open it"
    assert "line 13" not in lines, "a long description is cut with a hint to open it"
    assert "… c to read it all" in lines, "a long description is cut with a hint to open it"
    assert not any(line.startswith("comments") for line in lines), "a ticket without comments shows no comments line"
    cached = entries.ticket_entry(Ticket(key="OPS-7", summary="Ticket seven", status="Tareas por hacer"), [], STATED)
    assert cached.popup[1] == [], "a ticket cached before the detail fetch has nothing to open"
    shuffled = {**board([]), "my_tickets": [Ticket(key="A-1", summary="a", status="En proceso"),
                                            Ticket(key="A-2", summary="b", status="Tareas por hacer"),
                                            Ticket(key="A-3", summary="c", status="En proceso")]}
    assert [e.group for e in entries.entries(shuffled, STATED)["mine_tickets"]] == ["Todo", "In Progress", "In Progress"], \
        "my tickets from an older cache are regrouped by status"


def test_ticket_links():
    ticket = Ticket(key="ACME-1", summary="Ticket one", status="En proceso", detail=replace(
        TICKET_DETAIL, links=[*TICKET_DETAIL.links, {"relation": "relates to", "key": "ACME-3", "summary": "Third", "status": "Backlog"}]))
    lines = Content.from_markup(entries.ticket_entry(ticket, [], STATED).detail).plain.splitlines()
    start = lines.index("── links ──")
    assert lines[start + 1:start + 5] == ["• is blocked by ACME-2 (In review)", "  Ticket two", "• relates to ACME-3 (Backlog)", "  Third"], \
        "ticket links are a list, one item per link with its title below"
    assert not any(line.startswith("link ") for line in lines), "ticket links are a list, one item per link with its title below"


def test_escaping():
    assert (Content.from_markup(entries.link("https://github.com/acme/app/pull/1", "Fix path\\")).plain.rstrip(entries.ZERO_WIDTH_SPACE)
            == "Fix path\\"), "tui links keep a title ending in a backslash"
    site = config.Settings(team=["alice"], jira_project="ACME", github_user="me", github_org="acme",
                           jira_url='https://acme.atlassian.net/"><b>site</b>')
    rendered = (web.jira_link("ACME-9<i>", site) + web.tui_epic(EPIC, TICKETS, site)["detail"]
                + web.tui_ticket(TICKETS[0], [], site)["detail"])
    assert "<b>" not in rendered, "jira links escape the site and the key"
    assert "<i>" not in rendered, "jira links escape the site and the key"


def test_stardate():
    assert entries.stardate(dt.datetime(2026, 10, 25, 12, 0)) == "26298.5", "a stardate is the year, the day of the year and the tenth of the day"


def test_pr_comments():
    review = {"submittedAt": "2026-10-22T09:00:00Z", "state": "CHANGES_REQUESTED", "body": "Please split this", "author": {"login": "carol"}}
    pr = replace(PR_TWO, reviews=[*PR_TWO.reviews, review], commits=[{"committedDate": "2026-10-23T08:00:00Z"}], threads=[THREAD])
    detail = Content.from_markup(entries.pr_entry(pr, {}, STATED).detail).plain
    assert "comments 2 · c to open" in detail, "pr detail counts the comments and says how to open them"
    assert (all(text not in detail for text in
            ("Please split this", "app/models/order.rb", ".sum { |item|", "Rename qty to quantity"))), \
        "pr detail leaves the comments themselves to the popup"
    activity = detail[detail.index("── activity ──"):]
    assert activity.index("commit") < activity.index("approved"), "activity is newest first"
    assert "comments" not in Content.from_markup(entries.pr_entry(PR_ONE, {}, STATED).detail).plain, \
        "pr detail without comments has no comments line"


def test_conversation_comments():
    pr = replace(PR_TWO, reviews=[CHANGES], threads=[THREAD], conversation=[NOTE, REPLY])
    items = entries.review_items(pr)
    assert [str(item["row"]).splitlines()[0] for item in items] == ["comment", "changes requested", "comment", "order.rb:12"], \
        "conversation comments sit with the reviews by date, before the code threads"
    assert str(items[0]["row"]).splitlines()[1:] == ["alice", "Nice work, this reads well"], "a conversation comment shows its author and text"
    assert "alice commented" in Content.from_markup(items[0]["place"]).plain, "a conversation comment shows its author and text"
    assert "Nice work, this reads well" in Content.from_markup("\n".join(items[0]["comments"])).plain, \
        "a conversation comment shows its author and text"
    assert items[0]["url"] == NOTE["url"], "enter on a conversation comment opens that comment"
    assert "comments 4 · c to open" in Content.from_markup(entries.pr_entry(pr, {}, STATED).detail).plain, \
        "the detail counts conversation comments too"
