import datetime as dt
from dataclasses import replace
from pathlib import Path

import pytest
from textual.content import Content

from builders import EPIC, PR_ONE, PR_TWO, STATED, TICKETS
from tarkon import rows
from tarkon.domain import ages
from tarkon.tui import app as app_module
from tarkon.tui import entries, theme


def test_rows_view_model():
    from tarkon import rows
    from tarkon.tui import app as tui_app
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
    assert "app#1 Awaiting review" in tui, "the TUI shows the row data"
    assert Path(tui_app.__file__).with_name("app.tcss").exists(), "the TUI styles live in a tcss file the app loads"
    assert tui_app.TarkonApp.CSS_PATH == "app.tcss", "the TUI styles live in a tcss file the app loads"
    assert not tui_app.TarkonApp.CSS, "the TUI styles live in a tcss file the app loads"


def test_pr_rows():
    row = lambda pr: entries.cell_row(entries.pr_entry(pr, {}, STATED), app_module.PR_WIDTHS).plain
    assert "[ACME-1]" in row(PR_ONE), "team pr row shows the title's ticket code and the author"
    assert "alice" in row(PR_ONE), "team pr row shows the title's ticket code and the author"
    assert "[" not in row(replace(PR_ONE, title="No ticket")), "team pr row without a ticket code shows no code"
    assert "alice" in row(replace(PR_ONE, title="No ticket")), "team pr row without a ticket code shows no code"


def test_stardate():
    assert rows.stardate(dt.datetime(2026, 10, 25, 14, 32)) == "STARDATE 2610.25 · UPDATED 14:32", \
        "the LCARS masthead reads the year and month, the day, then the time of the last refresh"


def opened(days):
    return f"{dt.date.today() - dt.timedelta(days=days)}T10:00:00Z"


@pytest.mark.usefixtures("default_theme")
def test_lcars_puts_old_team_prs_first():
    prs = [replace(PR_ONE, repo="web", url="u1", created_at=opened(1)), replace(PR_TWO, repo="api", url="u2", created_at=opened(4)),
           replace(PR_ONE, repo="web", url="u3", created_at=opened(5)), replace(PR_TWO, repo="app", url="u4", created_at=opened(3))]
    found = {"prs": prs, "by_key": {}, "attention": [], "changes": [], "epics": [], "my_prs": [], "my_tickets": []}
    listed = entries.entries(found, STATED)["prs"]
    assert [(e.url, e.group, e.cells[-1][1]) for e in listed] == [("u3", None, "dim-right"), ("u2", None, "dim-right"),
                                                                 ("u4", None, "dim-right"), ("u1", None, "dim-right")], \
        "the default theme lists team PRs by age, days dimmed"
    theme.use_theme("okuda")
    listed = entries.entries(found, STATED)["prs"]
    assert [(e.url, e.group) for e in listed] == [("u3", "PRIORITY ONE"), ("u2", "PRIORITY ONE"), ("u4", "ROUTINE"), ("u1", "ROUTINE")], \
        "LCARS lists team PRs open more than three days as PRIORITY ONE, then the ROUTINE ones, oldest first in each"
    assert [e.cells[-1] for e in listed] == [("5d", "bad-alarm"), ("4d", "bad-alarm"), ("3d", "dim-right"), ("1d", "dim-right")], \
        "LCARS shows the days of a PRIORITY ONE PR in a red pill"


@pytest.mark.usefixtures("default_theme")
def test_lcars_segments_epic_bars():
    theme.use_theme("okuda")
    bar = entries.epic_entry(EPIC, TICKETS, STATED).cells[1][0]
    lcars = theme.THEMES["okuda"]
    assert [(bar.plain[s.start:s.end], str(s.style)) for s in bar.spans] == [("█ " * 5, lcars["ok"]), ("█ " * 5, lcars["line"])], \
        "LCARS splits epic progress into ten segments, done ones green"
    two_of_three = [TICKETS[1], TICKETS[1], TICKETS[0]]
    assert entries.epic_entry(EPIC, two_of_three, STATED).cells[1][0].plain.count("█") == 10, "LCARS splits epic progress into ten segments"
    assert entries.epic_entry(EPIC, two_of_three, STATED).cells[1][0].spans[0].end == 14, "LCARS rounds done segments to the nearest tenth"


@pytest.mark.usefixtures("default_theme")
def test_lcars_pills_fit_their_text():
    pr = replace(PR_ONE, created_at=opened(123), review_decision="CHANGES_REQUESTED")
    found = {"prs": [pr], "by_key": {}, "attention": [], "changes": [], "epics": [], "my_prs": [], "my_tickets": []}
    row = lambda: entries.cell_row(entries.entries(found, STATED)["prs"][0], app_module.widths("prs")).plain
    assert row().endswith("✗ ci ⚠ conflict 123d "), "the default theme keeps its plain cells"
    theme.use_theme("okuda")
    for label in ("◖ CHANGES REQUESTED ◗", "◖ CI ◗", "◖ CONFLICT ◗", "◖ 123D ◗"):
        assert label in row(), f"LCARS pads {label} inside its pill and gives the cell room for all of it"
