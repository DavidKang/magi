"""The rows the TUI and the html TUI design show for a PR or a ticket, as plain data each view formats its own way."""

import re

from . import board as g
from .fetch import days_since
from .jira import status_label


def pr_row(pr, by_key, settings):
    code = re.search(r"\[[A-Z][A-Z0-9]+-\d+\]", pr.title)
    return {"ref": f"{g.tui_repo(pr)}#{pr.number}", "repo": pr.repo, "number": pr.number, "url": pr.url, "title": pr.title,
            "code": code.group() if code else "", "author": pr.author["login"], "review": g.review_state(pr), "ci": pr.ci,
            "conflict": pr.mergeable == "CONFLICTING", "review_requested": bool(pr.review_requests), "age": days_since(pr.created_at),
            "tickets": [{"key": t.key, "url": settings.jira_browse + t.key, "status": t.status, "summary": t.summary}
                        for t in (by_key[k] for k in sorted(g.ticket_keys_in(pr, settings.jira_project)) if k in by_key)],
            "events": [{"at": c["committedDate"], "state": None, "author": None} for c in pr.commits]
            + [{"at": r["submittedAt"], "state": r["state"], "author": r["author"]["login"]} for r in pr.reviews]}


def ticket_row(ticket, prs, settings):
    # The TUI links a PR whose title names the ticket in brackets; the html design only one naming a key of the project.
    return {"key": ticket.key, "url": settings.jira_browse + ticket.key, "summary": ticket.summary, "status": status_label(ticket.status),
            "prs": [{"ref": f"{g.tui_repo(pr)}#{pr.number}", "url": pr.url, "review": g.review_state(pr)[1],
                     "project_key": ticket.key in g.ticket_keys_in(pr, settings.jira_project)}
                    for pr in prs if ticket.key in g.title_keys_in(pr, settings.jira_project)]}
