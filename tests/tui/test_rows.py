import datetime as dt
from dataclasses import replace
from pathlib import Path

import pytest
from textual.content import Content

from builders import EPIC, PR_ONE, PR_TWO, STATED, TICKETS, bare_board, make_pr
from magi import rows
from magi.domain import ages
from magi.tui import app as app_module
from magi.tui import entries, theme


def test_rows_view_model():
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


def test_styles_live_in_a_tcss_file():
    assert Path(app_module.__file__).with_name("app.tcss").exists(), "the TUI styles live in a tcss file the app loads"
    assert app_module.MagiApp.CSS_PATH == "app.tcss", "the TUI styles live in a tcss file the app loads"
    assert not app_module.MagiApp.CSS, "the TUI styles live in a tcss file the app loads"


def test_pr_rows():
    row = lambda pr, room=100: entries.cell_row(entries.pr_entry(pr, {}, STATED), app_module.widths("prs", room)).plain
    assert row(PR_ONE).startswith("[ACME-1] First change "), "a pr row starts with the PR's title"
    assert row(PR_ONE).rstrip().endswith(" app") and "#1" not in row(PR_ONE), "a pr row ends with its repo, without the PR number"
    assert len(row(PR_ONE)) == 100, "the title stretches with the box"
    assert row(replace(PR_ONE, title="A" * 90), 160).startswith("A" * 59 + "… "), "the title stops growing at 60 columns"
    assert len(row(PR_ONE, 160)) == 160 and row(PR_ONE, 160).rstrip().endswith(" app"), \
        "the repo sits at the right edge however wide the box, past the title's 60 columns"
    assert row(replace(PR_ONE, title="A" * 90)).startswith("A" * 35 + "… "), "a title longer than its room ends in an ellipsis"
    assert "alice" in row(PR_ONE), "a pr row shows its author"
    assert "red CI · conflict" in row(PR_ONE), "a pr row says only what blocks it"
    assert "✓ ci" not in row(PR_TWO) and "approved" in row(PR_TWO), "a pr row hides a green CI"


def test_stardate():
    assert rows.stardate(dt.datetime(2026, 10, 25, 14, 32)) == "STARDATE 2610.25 · UPDATED 14:32", \
        "the LCARS masthead reads the year and month, the day, then the time of the last refresh"


def opened(days):
    return f"{dt.date.today() - dt.timedelta(days=days)}T10:00:00Z"


def by_turn(number, days, **fields):
    green = {"ci": "passing", "mergeable": "MERGEABLE", "review_requests": [], "commits": []}
    return make_pr(**{**green, "url": f"u{number}", "repo": "web", "number": number, "title": f"Change {number}",
                      "created_at": opened(days), **fields})


@pytest.mark.usefixtures("default_theme")
def test_team_prs_are_grouped_by_turn():
    changes = {"state": "CHANGES_REQUESTED", "submittedAt": opened(5), "body": "", "author": {"login": "bob"}}
    asked, old = by_turn(2, 2), by_turn(7, 4)
    prs = [by_turn(1, 1), asked, by_turn(3, 5, reviews=[changes], mergeable="CONFLICTING"),
           by_turn(4, 3, review_decision="APPROVED"), by_turn(5, 6, is_draft=True), by_turn(6, 1, is_draft=True), old]
    found = bare_board(prs=prs, review_prs=[asked], my_prs=prs)
    listed = entries.entries(found, STATED)["prs"]
    assert [(e.url, e.group) for e in listed] == [("u2", "needs review"), ("u7", "needs review"), ("u1", "needs review"),
                                                 ("u3", "on the author"), ("u4", "ready to merge"), ("u5", "drafts"), ("u6", "drafts")], \
        "team PRs are grouped by whose turn it is: my review requests first, then oldest first in each group, drafts last"
    row = lambda entry: entries.cell_row(entry, app_module.widths("prs", 100)).plain
    assert "your review" in row(listed[0]), "a PR that asks for my review says so"
    assert "no review yet" in row(listed[1]), "a PR nobody reviewed says so"
    assert "changes · conflict" in row(listed[3]), "a PR on its author says what blocks it"
    assert row(listed[5]).startswith("Change 5 ") and "draft" in row(listed[5]), "a draft is a row like any other PR"
    assert [e.group for e in entries.entries(found, STATED)["mine_prs"]] == [None] * len(prs), "my PRs keep one row each, without groups"
    days = lambda: {e.url: e.cells[entries.DAYS_CELL] for e in entries.team_pr_entries([by_turn(8, 3), by_turn(9, 4)], {}, STATED, set())}
    assert days() == {"u8": ("3d", "dim-right"), "u9": ("4d", "bad-right")}, "a PR's days turn red only once it is open over three days"
    theme.use_theme("okuda")
    listed = entries.entries(found, STATED)["prs"]
    assert [e.group for e in listed] == ["NEEDS REVIEW"] * 3 + ["ON THE AUTHOR", "READY TO MERGE"] + ["DRAFTS"] * 2, \
        "LCARS writes the turn groups in capitals"
    assert days() == {"u8": ("3d", "dim-right"), "u9": ("4d", "bad-alarm")}, "LCARS turns a PR's days red only once it is open over three days"


@pytest.mark.usefixtures("default_theme")
@pytest.mark.parametrize("name, done, rest, tone, rule", [
    ("default", "█" * 10, "░" * 10, "dim", "epic progress is a block bar, done blocks green and the rest dim"),
    ("okuda", "█ " * 5, "█ " * 5, "line", "LCARS splits epic progress into ten segments, done ones green"),
    ("nerv", "█ " * 5, "█ " * 5, "raised", "nerv splits epic progress into segments like nerv-ui's sync bars, the rest dark")])
def test_epic_bars(name, done, rest, tone, rule):
    theme.use_theme(name)
    bar = entries.epic_entry(EPIC, TICKETS, STATED).cells[1][0]
    colours = theme.THEMES[name]
    assert [(bar.plain[s.start:s.end], str(s.style)) for s in bar.spans] == [(done, colours["ok"]), (rest, colours[tone])], rule


@pytest.mark.usefixtures("default_theme")
def test_lcars_epic_bars_round_to_tenths():
    theme.use_theme("okuda")
    two_of_three = [TICKETS[1], TICKETS[1], TICKETS[0]]
    assert entries.epic_entry(EPIC, two_of_three, STATED).cells[1][0].plain.count("█") == 10, "LCARS splits epic progress into ten segments"
    assert entries.epic_entry(EPIC, two_of_three, STATED).cells[1][0].spans[0].end == 14, "LCARS rounds done segments to the nearest tenth"


@pytest.mark.usefixtures("default_theme")
def test_lcars_pills_fit_their_text():
    pr = replace(PR_ONE, created_at=opened(123), review_decision="CHANGES_REQUESTED", ci="passing")
    row = lambda: entries.cell_row(entries.entries(bare_board(prs=[pr]), STATED)["prs"][0], app_module.widths("prs")).plain
    assert f"{'changes · conflict':<27} 123d" in row(), "the default theme keeps its plain cells"
    theme.use_theme("okuda")
    for label in (f"◖ {'CHANGES · CONFLICT':<27} ◗", "◖ 123D ◗"):
        assert label in row(), f"LCARS pads {label} inside its pill and gives the cell room for all of it"


def test_pr_ticket_keys():
    titled = make_pr(title="[ACME-99] Fix it", head_ref_name="ACME-100-fix")
    assert rows.pr_row(titled, {}, STATED)["keys"] == ["ACME-99", "ACME-100"], "a pr's ticket is the one its title names, before its branch's"
    branched = make_pr(title="Fix it", head_ref_name="ACME-100-and-ACME-99")
    assert rows.pr_row(branched, {}, STATED)["keys"] == ["ACME-99", "ACME-100"], "ticket keys sort by number, not as text"


@pytest.mark.usefixtures("default_theme")
@pytest.mark.parametrize("name", ["default", "okuda", "nerv"])
def test_longest_turn_label_fits(name):
    theme.use_theme(name)
    pr = make_pr(reviews=[{"state": "CHANGES_REQUESTED", "submittedAt": "2026-10-22T09:00:00Z", "author": {"login": "bob"}, "body": ""}],
                 commits=[], ci="failing", mergeable="CONFLICTING")
    entry = entries.team_pr_entries([pr], {}, STATED, set())[0]
    row = entries.cell_row(entry, app_module.widths("prs", 160)).plain
    assert "changes · red ci · conflict" in row.lower(), "the longest turn label shows whole in every theme"


@pytest.mark.usefixtures("default_theme")
def test_narrow_box_keeps_some_title():
    assert app_module.widths("prs", 50)[0] == app_module.NARROW_TITLE, "a box too narrow for the columns still shows ten columns of title"
