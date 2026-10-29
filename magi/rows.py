"""The rows the TUI shows for a PR or a ticket, as plain data the entries format."""

import datetime as dt
import re

from .domain.ages import days_since
from .domain.keys import ticket_keys_in, title_keys_in
from .domain.review import pr_events, review_state, turn
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


def key_rank(pr, key):
    """The keys a PR's title names come first, then by number: ACME-99 before ACME-100."""
    return not re.search(rf"\b{key}\b", pr.title, re.I), int(key.rsplit("-", 1)[1])


def pr_row(pr, by_key, settings):
    code = re.search(r"\[[A-Z][A-Z0-9]+-\d+\]", pr.title)
    keys = sorted(ticket_keys_in(pr, settings.jira_project), key=lambda key: key_rank(pr, key))
    return {"ref": f"{tui_repo(pr)}#{pr.number}", "repo": pr.repo, "number": pr.number, "url": pr.url, "title": pr.title,
            "code": code.group() if code else "", "author": pr.author["login"], "review": review_state(pr), "turn": turn(pr), "ci": pr.ci,
            "conflict": pr.mergeable == "CONFLICTING", "review_requested": bool(pr.review_requests), "age": days_since(pr.created_at), "keys": keys,
            "tickets": [{"key": t.key, "url": settings.jira_browse + t.key, "status": status_label(t.status), "summary": t.summary}
                        for t in (by_key[k] for k in keys if k in by_key)],
            "events": pr_events(pr)}


def ticket_row(ticket, prs, settings):
    return {"key": ticket.key, "url": settings.jira_browse + ticket.key, "summary": ticket.summary, "status": status_label(ticket.status),
            "prs": [{"ref": f"{tui_repo(pr)}#{pr.number}", "url": pr.url, "review": review_state(pr)[1]} for pr in prs_naming(ticket.key, prs, settings)]}


def prs_naming(key, prs, settings):
    return [pr for pr in prs if key in title_keys_in(pr, settings.jira_project)]
