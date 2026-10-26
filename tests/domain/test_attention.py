import datetime as dt
from dataclasses import replace

import pytest

from builders import PR_ONE, STATED, SUBJECT, TICKETS, make_pr, make_ticket
from magi.domain import ages, attention

QUIET_PR = make_pr(ci="passing", mergeable="MERGEABLE", review_decision="APPROVED")


@pytest.fixture
def today(monkeypatch):
    def set_today(day):
        class Day(dt.date):
            @classmethod
            def today(cls):
                return day
        monkeypatch.setattr(ages.dt, "date", Day)
    set_today(dt.date(2026, 10, 23))
    return set_today


def ticket_subject(ticket):
    return {"kind": "ticket", "url": STATED.jira_browse + ticket.key, "ref": ticket.key, "title": ticket.summary}


def reasons(tickets=(), prs=(), merged=None):
    return [item["reason"] for item in attention.attention_items(list(tickets), list(prs), merged or {}, STATED)]


def test_attention_items_are_data():
    tickets = [replace(TICKETS[0], prs=[PR_ONE])]
    assert (attention.attention_items(tickets, [], {}, STATED) == [
          {"subject": SUBJECT, "reason": "Open for review, but the ticket is still In progress. Move it to In review?"}]), \
        "attention items are data, never html"


def test_nothing_needs_attention_on_a_calm_board(today):
    tickets = [make_ticket(), make_ticket(key="ACME-2", column="review", prs=[QUIET_PR]),
               make_ticket(key="ACME-3", column="todo", assignee="Unassigned")]
    assert reasons(tickets, [QUIET_PR]) == [], "a ticket in progress without PRs, one in review with its PR and an unowned todo are fine"


def test_a_draft_does_not_ask_to_move_the_ticket():
    assert reasons([make_ticket(prs=[make_pr(is_draft=True)])]) == [], "only PRs open for review ask to move an In progress ticket"


def test_a_merged_pr_asks_to_move_a_ticket_with_no_open_pr():
    merged = {"kind": "pr", "url": "https://github.com/acme/app/pull/9", "ref": "app#9", "title": "[ACME-1] Done"}
    for column, status, shown in [("doing", "En proceso", "In Progress"), ("review", "En revisión", "In review")]:
        ticket = make_ticket(column=column, status=status)
        assert attention.attention_items([ticket], [], {"ACME-1": [merged]}, STATED) == [
            {"subject": merged, "reason": f"Merged, but the ticket is still {shown} with no other open PR. Move it?"}], \
            f"a merged PR flags its {column} ticket when no other PR is open, naming its status in English"
    assert reasons([make_ticket(prs=[make_pr(is_draft=True)])], merged={"ACME-1": [merged]}) == [], \
        "a merged PR stays quiet while another PR of the ticket is open"


def test_a_ticket_in_review_needs_a_pr():
    ticket = make_ticket(column="review", status="En revisión")
    assert attention.attention_items([ticket], [], {}, STATED) == [{"subject": ticket_subject(ticket), "reason": "In review with no open PR."}], \
        "a ticket in review with no PR, open or merged, is flagged"


def test_a_done_ticket_with_an_open_pr_is_flagged():
    ticket = make_ticket(column="done", status="Finalizado", prs=[QUIET_PR])
    assert reasons([ticket]) == ["Still open, but the ticket is already done."], "an open PR on a done ticket is flagged"


def test_an_active_ticket_needs_an_owner():
    for column in sorted(attention.ACTIVE_COLUMNS):
        ticket = make_ticket(column=column, assignee="Unassigned", prs=[make_pr(is_draft=True)])
        assert attention.attention_items([ticket], [], {}, STATED) == [{"subject": ticket_subject(ticket), "reason": "Active with no owner."}], \
            f"an unowned ticket in {column} is flagged"


def test_an_approved_pr_that_cannot_merge_is_flagged(today):
    assert reasons(prs=[replace(QUIET_PR, ci="failing")]) == ["Approved, but it has red CI."], "approved with red CI is flagged"
    assert reasons(prs=[replace(QUIET_PR, mergeable="CONFLICTING")]) == ["Approved, but it has conflicts."], "approved with conflicts is flagged"
    assert reasons(prs=[replace(QUIET_PR, ci="failing", mergeable="CONFLICTING")]) == ["Approved, but it has red CI."], \
        "red CI is named before conflicts"


def test_a_pr_waits_for_review_more_than_three_days(today):
    waiting = make_pr(created_at="2026-10-20T10:00:00Z", ci="passing", mergeable="MERGEABLE")
    assert reasons(prs=[waiting]) == [], "three days without review is still fine"
    today(dt.date(2026, 10, 24))
    assert reasons(prs=[waiting]) == ["4 days without any review."], "more than three days without review is flagged"
    assert reasons(prs=[replace(waiting, reviews=[{"state": "COMMENTED"}])]) == [], "a reviewed PR is not waiting"
