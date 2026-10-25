from builders import make_pr
from tarkon.domain.review import looks_ready_but_blocked, review_state


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
