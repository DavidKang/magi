import ast
import json
import subprocess
from pathlib import Path

from magi import config
from magi.domain.entities import Epic, PullRequest, Ticket, TicketDetail

ROOT = Path(__file__).resolve().parents[1]


def imported(path, package):
    """The modules a source file imports, its relative imports resolved against its package."""
    for node in ast.walk(ast.parse(Path(path).read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level:
            parts = package.split(".")
            yield ".".join(parts[:len(parts) - node.level + 1] + ([node.module] if node.module else []))
        elif isinstance(node, ast.ImportFrom):
            yield node.module


def outside(names, stdlib, packages):
    """The imported names that are neither allowed stdlib modules nor inside one of the packages."""
    return [name for name in names if name.split(".")[0] not in stdlib and not any((name + ".").startswith(p + ".") for p in packages)]


SETTINGS = {"team": ["alice", "bob"], "jira_project": "ACME", "github_user": "alice", "github_org": "acme",
            "jira_url": "https://acme.atlassian.net"}


def make_settings(**overrides):
    return config.Settings(**{**SETTINGS, **overrides})


STATED = make_settings()


def make_pr(**overrides):
    return PullRequest(**{
        "url": "https://github.com/acme/app/pull/1", "repo": "app", "number": 1, "title": "[ACME-1] First change",
        "author": {"login": "alice"}, "is_draft": False, "review_decision": "", "reviews": [], "review_requests": [{}],
        "created_at": "2026-10-20T10:00:00Z", "ci": "failing", "mergeable": "CONFLICTING", "head_ref_name": "ACME-1-x",
        "commits": [{"committedDate": "2026-10-21T10:00:00Z"}], "threads": [], "conversation": [],
        "updated_at": "2026-10-21T10:00:00Z", "head_ref_oid": "a1", **overrides})


def make_ticket(**overrides):
    return Ticket(**{"key": "ACME-1", "summary": "Ticket one", "status": "En proceso", "column": "doing", "assignee": "Ana", **overrides})


def make_ticket_detail(**overrides):
    return TicketDetail(**{
        "type": "Story", "priority": "Low", "labels": ["blocked"], "creator": "Bob",
        "created": "2026-10-08T16:12:45.341+0200", "updated": "2026-10-21T17:42:10.834+0200",
        "epic": {"key": "ACME-100", "summary": "Epic one"},
        "links": [{"relation": "is blocked by", "key": "ACME-2", "summary": "Ticket two", "status": "En revisión"}],
        "description": "Context\n\nUse the new reason column.",
        "comments": [{"id": "10", "author": "Carol", "created": "2026-10-20T10:00:00.000+0200", "body": "Looks good"}], **overrides})


def make_epic(**overrides):
    return Epic(**{"key": "ACME-100", "summary": "Epic one", "status": "Developing", "owner": "Ana", **overrides})


PR_ONE = make_pr()
PR_TWO = make_pr(url="https://github.com/acme/billing-reconciliation-service/pull/2", repo="billing-reconciliation-service",
                 number=2, title="[ACME-2] Second change", author={"login": "bob"}, review_decision="APPROVED",
                 reviews=[{"submittedAt": "2026-10-22T09:00:00Z", "state": "APPROVED", "body": "", "author": {"login": "alice"}}],
                 review_requests=[], created_at="2026-10-21T10:00:00Z", ci="passing", mergeable="MERGEABLE", head_ref_name="ACME-2-y",
                 commits=[], updated_at="2026-10-22T09:00:00Z", head_ref_oid="b2")
PR_THREE = make_pr(url="https://github.com/acme/app/pull/3", number=3, title="[ACME-3] Third change",
                   created_at="2026-10-23T10:00:00Z", head_ref_oid="c3")
TICKETS = [make_ticket(), make_ticket(key="ACME-2", summary="Ticket two", status="Finalizado", column="done")]
TICKET_DETAIL = make_ticket_detail()
EPIC = make_epic()
SUBJECT = {"kind": "pr", "url": "https://github.com/acme/app/pull/1", "ref": "app#1", "title": "[ACME-1] First change"}


def board(prs):
    return {"epics": [EPIC], "tickets_by_epic": {"ACME-100": TICKETS}, "by_key": {t.key: t for t in TICKETS}, "prs": prs, "review_prs": [],
            "my_prs": [PR_ONE], "my_tickets": [Ticket(key="OPS-7", summary="Ticket seven", status="Tareas por hacer"),
                                             Ticket(key="ACME-1", summary="Ticket one", status="En proceso", detail=TICKET_DETAIL)],
            "attention": [{"subject": SUBJECT, "reason": "Open for review, but the ticket is still In progress. Move it to In review?"}],
            "changes": [{"at": "2026-10-24T02:04", "tone": "commented", "label": "New PR", "subject": SUBJECT, "note": None, "aside": None,
                         "item": PR_ONE.url}]}


def settings_file(cache, settings=SETTINGS):
    path = cache.with_name("config.json")
    path.write_text(json.dumps(settings))
    return path


def failing_load():
    raise subprocess.CalledProcessError(1, ["gh", "search", "prs", "--json", "number"], stderr="API rate limit exceeded\n")


HUNK = "@@ -1,5 +1,5 @@\n def total\n   items\n-    .sum(&:price)\n+    .sum { |item| item.price * item.qty }\n end"
THREAD = {"isResolved": False, "isOutdated": False, "path": "app/models/order.rb", "line": 12,
          "comments": [{"author": {"login": "carol"}, "body": "Rename qty to quantity", "createdAt": "2026-10-22T09:05:00Z", "diffHunk": HUNK,
                        "url": "https://github.com/acme/app/pull/2#discussion_r1"},
                       {"author": {"login": "bob"}, "body": "Done", "createdAt": "2026-10-22T10:00:00Z", "diffHunk": HUNK,
                        "url": "https://github.com/acme/app/pull/2#discussion_r2"}]}
OUTDATED = {"isResolved": False, "isOutdated": True, "path": "README.md", "line": None,
            "comments": [{"author": {"login": "alice"}, "body": "Typo", "createdAt": "2026-10-22T11:00:00Z",
                          "diffHunk": "@@ -1,2 +1,2 @@\n # App\n-Teh app", "url": "https://github.com/acme/app/pull/2#discussion_r3"}]}
NOTE = {"author": {"__typename": "User", "login": "alice"}, "body": "Nice work, this reads well", "createdAt": "2026-10-22T08:00:00Z",
        "url": "https://github.com/acme/app/pull/2#issuecomment-1"}
REPLY = {**NOTE, "author": {"__typename": "User", "login": "bob"}, "body": "Thanks!", "createdAt": "2026-10-22T09:30:00Z",
         "url": "https://github.com/acme/app/pull/2#issuecomment-2"}
CHANGES = {"submittedAt": "2026-10-22T09:00:00Z", "state": "CHANGES_REQUESTED", "body": "Please split this", "author": {"login": "carol"}}


def light_node(pr, updated="2026-10-24T10:00:00Z", ci="SUCCESS"):
    owner_repo = pr.url.split("/")[3] + "/" + pr.url.split("/")[4]
    return {"url": pr.url, "number": pr.number, "updatedAt": updated, "title": pr.title, "headRefName": pr.head_ref_name,
            "mergeable": pr.mergeable, "author": pr.author, "repository": {"nameWithOwner": owner_repo},
            "head": {"nodes": [{"commit": {"statusCheckRollup": {"state": ci} if ci else None}}]}}


def pr_node(number, rollup):
    resolved = {**THREAD, "isResolved": True, "path": "app/old.rb"}
    bots = [{**NOTE, "author": {"__typename": "Bot", "login": "github-actions"}}, {**NOTE, "author": {"__typename": "User", "login": "deploybot"}}]
    return {"pullRequest": {
        "number": number, "title": "x", "url": f"https://github.com/acme/app/pull/{number}", "author": {"login": "alice"},
        "updatedAt": "2026-10-22T10:00:00Z", "headRefName": "x", "headRefOid": "h", "isDraft": False, "createdAt": "2026-10-20T10:00:00Z",
        "reviewDecision": None, "mergeable": "MERGEABLE",
        "reviewRequests": {"nodes": [{"requestedReviewer": {"__typename": "User"}}]}, "reviews": {"nodes": [CHANGES]},
        "commits": {"nodes": [{"commit": {"committedDate": "2026-10-21T10:00:00Z"}}, {"commit": {"committedDate": "2026-10-22T10:00:00Z"}}]},
        "head": {"nodes": [{"commit": {"statusCheckRollup": rollup}}]},
        "reviewThreads": {"nodes": [{**t, "comments": {"nodes": t["comments"]}} for t in (THREAD, resolved)]},
        "comments": {"nodes": [*bots, NOTE]}}}


def ticket_view(key):
    return {"key": key, "fields": {
        "summary": "S", "issuetype": {"name": "Story"}, "priority": {"name": "Low"}, "labels": ["blocked"], "creator": {"displayName": "Bob"},
        "created": "2026-10-08T16:12:45.341+0200", "updated": "2026-10-21T17:42:10.834+0200",
        "parent": {"key": "ACME-100", "fields": {"summary": "Epic one"}},
        "issuelinks": [{"type": {"inward": "is blocked by", "outward": "blocks"},
                        "inwardIssue": {"key": "ACME-2", "fields": {"summary": "Ticket two", "status": {"name": "En revisión"}}}}],
        "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Context"}]},
                                                   {"type": "paragraph", "content": [{"type": "text", "text": "Use the new reason column."}]}]},
        "comment": {"comments": [{"id": "10", "author": {"displayName": "Carol"}, "created": "2026-10-20T10:00:00.000+0200",
                                  "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Looks good"}]}]}}]}}}
