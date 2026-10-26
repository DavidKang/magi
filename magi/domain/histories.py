"""The PR histories a change's timeline shows: told by the PRs on the board, and kept for the ones that left it."""

from .review import pr_events


def pr_histories(prs, saved):
    """Each PR's history: told by the PRs at hand, and as saved for the ones that left the board."""
    return {**saved, **{pr.url: pr_events(pr) for pr in prs}}


def kept_histories(saved, changes):
    """The saved histories one of the changes still shows."""
    shown = {c["group"] for c in changes}
    return {url: history for url, history in saved.items() if url in shown}
