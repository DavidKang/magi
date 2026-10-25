"""The rows the TUI shows for a PR or a ticket, as plain data the entries format."""

import datetime as dt
import re

from .domain.ages import days_since
from .domain.keys import ticket_keys_in, title_keys_in
from .domain.review import review_state, turn
from .domain.status import status_label

TUI_REVIEW = {"approved": "ok", "changes": "bad", "waiting": "warn", "commented": "blue", "draft": "dim"}
TUI_REVIEW_EVENTS = {"APPROVED": "ok", "CHANGES_REQUESTED": "bad"}
TUI_REPO_ALIASES = {}


def stardate(when):
    return f"STARDATE {when:%y%m}.{when:%d} · UPDATED {when:%H:%M}"


def tui_repo(pr):
    return TUI_REPO_ALIASES.get(pr.repo, pr.repo)


def local(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()


def local_time(iso):
    return local(iso).strftime("%b %d %H:%M")


def pr_row(pr, by_key, settings):
    code = re.search(r"\[[A-Z][A-Z0-9]+-\d+\]", pr.title)
    return {"ref": f"{tui_repo(pr)}#{pr.number}", "repo": pr.repo, "number": pr.number, "url": pr.url, "title": pr.title,
            "code": code.group() if code else "", "author": pr.author["login"], "review": review_state(pr), "turn": turn(pr), "ci": pr.ci,
            "conflict": pr.mergeable == "CONFLICTING", "review_requested": bool(pr.review_requests), "age": days_since(pr.created_at),
            "tickets": [{"key": t.key, "url": settings.jira_browse + t.key, "status": t.status, "summary": t.summary}
                        for t in (by_key[k] for k in sorted(ticket_keys_in(pr, settings.jira_project)) if k in by_key)],
            "events": [{"at": c["committedDate"], "state": None, "author": None} for c in pr.commits]
            + [{"at": r["submittedAt"], "state": r["state"], "author": r["author"]["login"]} for r in pr.reviews]}


def ticket_row(ticket, prs, settings):
    return {"key": ticket.key, "url": settings.jira_browse + ticket.key, "summary": ticket.summary, "status": status_label(ticket.status),
            "prs": [{"ref": f"{tui_repo(pr)}#{pr.number}", "url": pr.url, "review": review_state(pr)[1]}
                    for pr in prs if ticket.key in title_keys_in(pr, settings.jira_project)]}
