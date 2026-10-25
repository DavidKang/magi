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


def verdicts(reviews):
    """Each reviewer's latest approval or change request: a later comment does not undo it."""
    return set({review["author"]["login"]: review["state"] for review in reviews if review["state"] in ("APPROVED", "CHANGES_REQUESTED")}.values())


def review_state(pr):
    """Approved once someone approves and nobody asks for changes, even while GitHub still requires more reviews."""
    if pr.is_draft:
        return "draft", "Draft"
    given = verdicts(pr.reviews)
    if pr.review_decision == "CHANGES_REQUESTED" or "CHANGES_REQUESTED" in given:
        return "changes", "Changes requested"
    if pr.review_decision == "APPROVED" or "APPROVED" in given:
        return "approved", "Approved"
    if pr.reviews:
        return "commented", "Commented"
    return "waiting", "Awaiting review"
