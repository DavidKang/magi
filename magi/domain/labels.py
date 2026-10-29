"""Jira labels the board reads a meaning into."""

BLOCKED_LABEL = "blocked"


def blocked(ticket):
    return BLOCKED_LABEL in ticket.detail.labels
