import pytest

from builders import make_pr
from magi.domain.review import CONDITIONS, condition, looks_ready_but_blocked, pr_events, review_state, turn


def test_review_state_reads_the_pr():
    states = {name: review_state(make_pr(**fields)) for name, fields in {
        "draft": {"is_draft": True, "review_decision": "APPROVED"},
        "approved": {"review_decision": "APPROVED"},
        "changes": {"review_decision": "CHANGES_REQUESTED", "reviews": [{"state": "CHANGES_REQUESTED", "author": {"login": "bob"}}]},
        "commented": {"reviews": [{"state": "COMMENTED"}]},
        "waiting": {}}.items()}
    assert states == {"draft": ("draft", "Draft"), "approved": ("approved", "Approved"),
                      "changes": ("changes", "Changes requested"), "commented": ("commented", "Commented"),
                      "waiting": ("waiting", "Awaiting review")}, "a draft wins over its decision, then the decision, then any review"


def review(login, state):
    return {"state": state, "author": {"login": login}}


@pytest.mark.parametrize("decision, reviews, state", [
    ("REVIEW_REQUIRED", [review("alice", "APPROVED")], "approved"),
    ("REVIEW_REQUIRED", [review("alice", "APPROVED"), review("bob", "CHANGES_REQUESTED")], "changes"),
    ("APPROVED", [review("alice", "APPROVED"), review("bob", "CHANGES_REQUESTED")], "changes"),
    ("REVIEW_REQUIRED", [review("bob", "CHANGES_REQUESTED"), review("bob", "APPROVED")], "approved"),
    ("REVIEW_REQUIRED", [review("alice", "APPROVED"), review("alice", "COMMENTED")], "approved"),
    ("REVIEW_REQUIRED", [review("alice", "DISMISSED"), review("bob", "COMMENTED")], "commented")])
def test_review_state_counts_each_reviewers_last_verdict(decision, reviews, state):
    assert review_state(make_pr(review_decision=decision, reviews=reviews))[0] == state, \
        "a PR is approved when someone approved and nobody asks for changes, whatever GitHub still requires"


def test_ready_but_blocked_needs_approval_and_a_blocker():
    approved = {"review_decision": "APPROVED", "ci": "passing", "mergeable": "MERGEABLE"}
    assert not looks_ready_but_blocked(make_pr(**approved)), "approved with green CI and no conflicts can merge"
    assert looks_ready_but_blocked(make_pr(**{**approved, "ci": "failing"})), "approved with red CI is blocked"
    assert looks_ready_but_blocked(make_pr(**{**approved, "mergeable": "CONFLICTING"})), "approved with conflicts is blocked"
    assert not looks_ready_but_blocked(make_pr(ci="failing", mergeable="CONFLICTING")), "a PR nobody approved is not ready"


def test_condition_is_the_worst_open_pr():
    green = make_pr(review_decision="APPROVED", ci="passing", mergeable="MERGEABLE")
    mine, theirs = {"author": {"login": "alice"}}, {"author": {"login": "bob"}}

    def level(*prs):
        return CONDITIONS[condition(list(prs), "alice")]
    assert level() == "CONDITION GREEN", "a board with no PRs is all good"
    assert level(green, make_pr(is_draft=True, **mine)) == "CONDITION GREEN", "approved, green and clean PRs are all good; drafts do not count"
    assert level(green, make_pr(review_decision="APPROVED", ci="running", mergeable="MERGEABLE")) == "YELLOW ALERT", "a pending CI raises a yellow alert"
    assert level(green, make_pr(ci="passing", mergeable="MERGEABLE")) == "YELLOW ALERT", "a PR in review raises a yellow alert"
    assert level(make_pr(review_decision="APPROVED", ci="failing", mergeable="MERGEABLE", **mine)) == "RED ALERT", \
        "a failing CI on one of my PRs raises a red alert"
    assert level(make_pr(ci="running"), make_pr(review_decision="APPROVED", ci="passing", mergeable="CONFLICTING", **mine)) == "RED ALERT", \
        "a blocked PR of mine raises a red alert over any yellow one"
    assert level(green, make_pr(review_decision="APPROVED", ci="failing", mergeable="MERGEABLE", **theirs)) == "YELLOW ALERT", \
        "someone else's failing PR only raises a yellow alert, even next to a healthy PR of mine"
    assert level(green, make_pr(review_decision="APPROVED", ci="passing", mergeable="CONFLICTING", **theirs)) == "YELLOW ALERT", \
        "someone else's blocked PR only raises a yellow alert, even next to a healthy PR of mine"


def test_turn_reads_whose_move_a_pr_waits_on():
    changes = {"state": "CHANGES_REQUESTED", "submittedAt": "2026-10-22T09:00:00Z", "author": {"login": "bob"}}
    green = {"ci": "passing", "mergeable": "MERGEABLE"}
    cases = {
        "draft": ({"is_draft": True, **green}, ("drafts", "draft")),
        "approved and green": ({"review_decision": "APPROVED", **green}, ("ready to merge", "approved")),
        "approved, CI running": ({"review_decision": "APPROVED", **green, "ci": "running"}, ("ready to merge", "approved · CI running")),
        "approved, red CI": ({"review_decision": "APPROVED", **green, "ci": "failing"}, ("on the author", "approved · red CI")),
        "changes requested": ({"reviews": [changes], **green, "commits": []}, ("on the author", "changes requested")),
        "changes and conflict": ({"reviews": [changes], "ci": "passing", "mergeable": "CONFLICTING", "commits": []},
                                 ("on the author", "changes · conflict")),
        "pushed after the changes": ({"reviews": [changes], **green, "commits": [{"committedDate": "2026-10-23T09:00:00Z"}]},
                                     ("needs review", "re-review")),
        "commit before the changes": ({"reviews": [changes], **green, "commits": [{"committedDate": "2026-10-21T09:00:00Z"}]},
                                      ("on the author", "changes requested")),
        "red CI, no verdict": ({"ci": "failing", "mergeable": "MERGEABLE"}, ("on the author", "red CI")),
        "approved, conflict": ({"review_decision": "APPROVED", "ci": "passing", "mergeable": "CONFLICTING"}, ("on the author", "approved · conflict")),
        "approved, red CI and conflict": ({"review_decision": "APPROVED", "ci": "failing", "mergeable": "CONFLICTING"},
                                          ("on the author", "red CI · conflict")),
        "changes, red CI and conflict": ({"reviews": [changes], "ci": "failing", "mergeable": "CONFLICTING", "commits": []},
                                         ("on the author", "changes · red CI · conflict")),
        "answered, red CI": ({"reviews": [changes], **green, "ci": "failing", "commits": [{"committedDate": "2026-10-23T09:00:00Z"}]},
                             ("on the author", "red CI")),
        "answered, conflict": ({"reviews": [changes], **green, "mergeable": "CONFLICTING",
                                "commits": [{"committedDate": "2026-10-23T09:00:00Z"}]}, ("on the author", "conflict")),
        "asked again after the push": ({"reviews": [changes, {**changes, "submittedAt": "2026-10-24T09:00:00Z"}], **green,
                                        "commits": [{"committedDate": "2026-10-23T09:00:00Z"}]}, ("on the author", "changes requested")),
        "commit at the changes' time": ({"reviews": [changes], **green, "commits": [{"committedDate": "2026-10-22T09:00:00Z"}]},
                                        ("on the author", "changes requested")),
        "only comments": ({"reviews": [{"state": "COMMENTED"}], **green}, ("needs review", "comments, no verdict")),
        "no review, CI running": ({**green, "ci": "running"}, ("needs review", "no review yet")),
        "no review": (green, ("needs review", "no review yet")),
    }
    for name, (fields, expected) in cases.items():
        assert turn(make_pr(**fields)) == expected, f"{name}: only red CI, a conflict or unanswered changes put a PR on its author"


def test_pr_events_leave_out_a_review_not_submitted():
    pr = make_pr(reviews=[{"submittedAt": None, "state": "PENDING", "author": {"login": "alice"}},
                          {"submittedAt": "2026-10-22T10:00:00Z", "state": "APPROVED", "author": {"login": "bob"}}])
    assert [event["author"] for event in pr_events(pr)] == [None, "bob"], "a review not submitted yet has no time, so it is no event"
