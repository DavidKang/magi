import re
from dataclasses import replace
from pathlib import Path

from textual.content import Content

from builders import PR_ONE, PR_TWO, STATED, TICKETS
from tarkon import config
from tarkon.domain import ages
from tarkon.tui import app as app_module
from tarkon.tui import entries


def test_rows_view_model():
    from tarkon import rows
    from tarkon.html import page
    from tarkon.tui import app as tui_app
    config.use(None)
    ticket = TICKETS[0]
    row = rows.pr_row(PR_ONE, {ticket.key: ticket}, STATED)
    assert row["ref"] == "app#1", "a pr row is plain data built from the settings passed in"
    assert row["url"] == PR_ONE.url, "a pr row is plain data built from the settings passed in"
    assert row["author"] == "alice", "a pr row is plain data built from the settings passed in"
    assert row["review"] == ("waiting", "Awaiting review"), "a pr row is plain data built from the settings passed in"
    assert row["ci"] == "failing", "a pr row is plain data built from the settings passed in"
    assert row["conflict"], "a pr row is plain data built from the settings passed in"
    assert row["review_requested"], "a pr row is plain data built from the settings passed in"
    assert row["age"] == ages.days_since(PR_ONE.created_at), "a pr row is plain data built from the settings passed in"
    assert (row["tickets"] == [{"key": "ACME-1", "url": "https://acme.atlassian.net/browse/ACME-1", "status": "En proceso",
                                    "summary": "Ticket one"}]), "a pr row is plain data built from the settings passed in"
    linked = rows.ticket_row(ticket, [PR_ONE, PR_TWO], STATED)
    assert linked["key"] == "ACME-1", "a ticket row is plain data with its linked prs"
    assert linked["url"] == "https://acme.atlassian.net/browse/ACME-1", "a ticket row is plain data with its linked prs"
    assert linked["status"] == "In Progress", "a ticket row is plain data with its linked prs"
    assert [pr["ref"] for pr in linked["prs"]] == ["app#1"], "a ticket row is plain data with its linked prs"
    assert linked["prs"][0]["review"] == "Awaiting review", "a ticket row is plain data with its linked prs"
    tui = Content.from_markup(entries.ticket_entry(ticket, [PR_ONE], STATED).detail).plain
    html = re.sub(r"<[^>]+>", "", page.tui_ticket(ticket, [PR_ONE], STATED)["detail"])
    assert all("app#1 Awaiting review" in text for text in (tui, html)), "the TUI and the html TUI design show the same row data"
    assert Path(tui_app.__file__).with_name("app.tcss").exists(), "the TUI styles live in a tcss file the app loads"
    assert tui_app.TarkonApp.CSS_PATH == "app.tcss", "the TUI styles live in a tcss file the app loads"
    assert not tui_app.TarkonApp.CSS, "the TUI styles live in a tcss file the app loads"
    assert Path(page.__file__).with_name("template.html").exists(), "the html template is read from its package"


def test_pr_rows():
    row = lambda pr: entries.cell_row(entries.pr_entry(pr, {}, STATED), app_module.PR_WIDTHS).plain
    assert "[ACME-1]" in row(PR_ONE), "team pr row shows the title's ticket code and the author"
    assert "alice" in row(PR_ONE), "team pr row shows the title's ticket code and the author"
    assert "[" not in row(replace(PR_ONE, title="No ticket")), "team pr row without a ticket code shows no code"
    assert "alice" in row(replace(PR_ONE, title="No ticket")), "team pr row without a ticket code shows no code"
