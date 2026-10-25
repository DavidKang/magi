from builders import make_pr
from tarkon.domain.review import CONDITIONS, condition, looks_ready_but_blocked, review_state


def test_review_state_reads_the_pr():
    states = {name: review_state(make_pr(**fields)) for name, fields in {
        "draft": {"is_draft": True, "review_decision": "APPROVED"},
        "approved": {"review_decision": "APPROVED"},
        "changes": {"review_decision": "CHANGES_REQUESTED", "reviews": [{"state": "CHANGES_REQUESTED"}]},
        "commented": {"reviews": [{"state": "COMMENTED"}]},
        "waiting": {}}.items()}
    assert states == {"draft": ("draft", "Draft"), "approved": ("approved", "Approved"),
                      "changes": ("changes", "Changes requested"), "commented": ("commented", "Commented"),
                      "waiting": ("waiting", "Awaiting review")}, "a draft wins over its decision, then the decision, then any review"


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
