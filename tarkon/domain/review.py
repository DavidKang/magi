"""Where a PR stands: its review, and its CI as a tone and a label."""

CI_LABELS = {"failing": ("changes", "CI red"), "running": ("commented", "CI running"),
             "passing": ("approved", "CI green"), "none": ("draft", "No CI")}

CONDITIONS = {"green": "CONDITION GREEN", "yellow": "YELLOW ALERT", "red": "RED ALERT"}


def condition(prs, me):
    """The board's alert level: red while one of my open PRs fails CI or conflicts, yellow while any open PR has trouble or waits on CI or review."""
    open_prs = [pr for pr in prs if not pr.is_draft]
    troubled = [pr for pr in open_prs if pr.ci == "failing" or pr.mergeable == "CONFLICTING"]
    if any(pr.author["login"] == me for pr in troubled):
        return "red"
    if troubled or any(pr.ci == "running" or review_state(pr)[0] != "approved" for pr in open_prs):
        return "yellow"
    return "green"


def looks_ready_but_blocked(pr):
    return review_state(pr)[0] == "approved" and (pr.ci == "failing" or pr.mergeable == "CONFLICTING")


def review_state(pr):
    if pr.is_draft:
        return "draft", "Draft"
    if pr.review_decision == "APPROVED":
        return "approved", "Approved"
    if pr.review_decision == "CHANGES_REQUESTED":
        return "changes", "Changes requested"
    if pr.reviews:
        return "commented", "Commented"
    return "waiting", "Awaiting review"
