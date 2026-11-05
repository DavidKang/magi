import ast
import json
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from textual.widgets import OptionList

from magi import config
from magi.domain.entities import Epic, PullRequest, Ticket, TicketDetail
from magi.domain.review import pr_events
from magi.tui.app import MagiApp

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


SETTINGS = {"team": ["bulma", "goku"], "jira_project": "KAME", "github_user": "bulma", "github_org": "capsulecorp",
            "jira_url": "https://capsulecorp.atlassian.net"}


def make_settings(**overrides):
    return config.Settings(**{**SETTINGS, **overrides})


STATED = make_settings()


def make_pr(**overrides):
    return PullRequest(**{
        "url": "https://github.com/capsulecorp/radar/pull/1", "repo": "radar", "number": 1, "title": "[KAME-1] Charge the Kamehameha",
        "author": {"login": "bulma"}, "is_draft": False, "review_decision": "", "reviews": [], "review_requests": [{}],
        "created_at": "2026-10-20T10:00:00Z", "ci": "failing", "mergeable": "CONFLICTING", "head_ref_name": "KAME-1-x",
        "commits": [{"committedDate": "2026-10-21T10:00:00Z"}], "threads": [], "conversation": [],
        "updated_at": "2026-10-21T10:00:00Z", "head_ref_oid": "a1", "failed_checks": [], "conflicts": [],
        **overrides})


def make_ticket(**overrides):
    return Ticket(**{"key": "KAME-1", "summary": "Find the dragon balls", "status": "En proceso", "column": "doing", "assignee": "Chichi", **overrides})


def make_ticket_detail(**overrides):
    return TicketDetail(**{
        "type": "Story", "priority": "Low", "labels": ["blocked"], "creator": "Goku",
        "created": "2026-10-08T16:12:45.341+0200", "updated": "2026-10-21T17:42:10.834+0200",
        "epic": {"key": "KAME-100", "summary": "Frieza Saga"},
        "links": [{"relation": "is blocked by", "key": "KAME-2", "summary": "Train with King Kai", "status": "En revisión"}],
        "description": "Context\n\nGather all seven dragon balls.",
        "comments": [{"id": "10", "author": "Vegeta", "created": "2026-10-20T10:00:00.000+0200", "body": "Over 9000, looks good"}], **overrides})


def make_epic(**overrides):
    return Epic(**{"key": "KAME-100", "summary": "Frieza Saga", "status": "Developing", "owner": "Chichi", **overrides})


PR_ONE = make_pr()
PR_TWO = make_pr(url="https://github.com/capsulecorp/hyperbolic-time-chamber-portal/pull/2", repo="hyperbolic-time-chamber-portal",
                 number=2, title="[KAME-2] Charge the Spirit Bomb", author={"login": "goku"}, review_decision="APPROVED",
                 reviews=[{"submittedAt": "2026-10-22T09:00:00Z", "state": "APPROVED", "body": "", "author": {"login": "bulma"}}],
                 review_requests=[], created_at="2026-10-21T10:00:00Z", ci="passing", mergeable="MERGEABLE", head_ref_name="KAME-2-y",
                 commits=[], updated_at="2026-10-22T09:00:00Z", head_ref_oid="b2")
PR_THREE = make_pr(url="https://github.com/capsulecorp/radar/pull/3", number=3, title="[KAME-3] Summon Shenron",
                   created_at="2026-10-23T10:00:00Z", head_ref_oid="c3")
# A PR for each alert level, in the order green, yellow, red: make_pr's own PR fails its CI and conflicts.
ALERT_PRS = {"ok": make_pr(review_decision="APPROVED", ci="passing", mergeable="MERGEABLE"), "warn": make_pr(ci="passing", mergeable="MERGEABLE"),
             "bad": make_pr()}
TICKETS = [make_ticket(), make_ticket(key="KAME-2", summary="Train with King Kai", status="Finalizado", column="done")]
TICKET_DETAIL = make_ticket_detail()
EPIC = make_epic()
SUBJECT = {"kind": "pr", "url": "https://github.com/capsulecorp/radar/pull/1", "ref": "radar#1", "title": "[KAME-1] Charge the Kamehameha", "author": "bulma"}


def board(prs):
    return {"epics": [EPIC], "tickets_by_epic": {"KAME-100": TICKETS}, "by_key": {t.key: t for t in TICKETS}, "prs": prs, "review_prs": [],
            "my_prs": [PR_ONE], "my_tickets": [Ticket(key="RED-7", summary="Raid the Red Ribbon", status="Tareas por hacer"),
                                             Ticket(key="KAME-1", summary="Find the dragon balls", status="En proceso", detail=TICKET_DETAIL)],
            "kanban": [Ticket(key="KAME-1", summary="Find the dragon balls", status="En proceso", assignee="Chichi", detail=TICKET_DETAIL)],
            "changes": [{"at": "2026-10-24T02:04", "tone": "commented", "label": "New PR", "subject": SUBJECT, "note": None, "aside": None, "told": False,
                         "item": PR_ONE.url, "group": PR_ONE.url}],
            "histories": {pr.url: pr_events(pr) for pr in prs}}


def bare_board(**sections):
    """A board with nothing on it but the sections given."""
    return {"prs": [], "review_prs": [], "by_key": {}, "kanban": [], "changes": [], "epics": [], "my_prs": [], "my_tickets": [], "histories": {},
            **sections}


def settings_file(cache, settings=SETTINGS):
    path = cache.with_name("config.json")
    path.write_text(json.dumps(settings))
    return path


def magi_app(cache, load=lambda: board([PR_ONE]), theme=None, **options):
    """The app on a fake load; unless a config path is given, its settings, in the theme given, are saved next to the cache."""
    if "config_path" not in options:
        options["config_path"] = settings_file(cache, SETTINGS if theme is None else {**SETTINGS, "theme": theme})
    return MagiApp(load=load, **{"opener": print, "copier": print, "clock": lambda: 1000.0, "cache": cache, **options})


@asynccontextmanager
async def started(app, size=(160, 40)):
    """The app running, its first refresh done and drawn."""
    async with app.run_test(size=size) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        yield pilot


async def pick_theme(pilot, name):
    await pilot.press("t")
    await pilot.pause()
    choices = pilot.app.screen.query_one("#theme-list", OptionList)
    choices.highlighted = choices.get_option_index(name)
    await pilot.press("enter")
    await pilot.pause()


def failing_load():
    raise subprocess.CalledProcessError(1, ["gh", "search", "prs", "--json", "number"], stderr="API rate limit exceeded\n")


HUNK = "@@ -1,5 +1,5 @@\n def total\n   items\n-    .sum(&:price)\n+    .sum { |item| item.price * item.qty }\n end"
THREAD = {"isResolved": False, "isOutdated": False, "path": "app/models/senzu_bean.rb", "line": 12,
          "comments": [{"author": {"login": "vegeta"}, "body": "Rename qty to senzu_count", "createdAt": "2026-10-22T09:05:00Z", "diffHunk": HUNK,
                        "url": "https://github.com/capsulecorp/radar/pull/2#discussion_r1"},
                       {"author": {"login": "goku"}, "body": "Done, Vegeta", "createdAt": "2026-10-22T10:00:00Z", "diffHunk": HUNK,
                        "url": "https://github.com/capsulecorp/radar/pull/2#discussion_r2"}]}
OUTDATED = {"isResolved": False, "isOutdated": True, "path": "README.md", "line": None,
            "comments": [{"author": {"login": "bulma"}, "body": "Typo in Kamehameha", "createdAt": "2026-10-22T11:00:00Z",
                          "diffHunk": "@@ -1,2 +1,2 @@\n # Radar\n-Teh radar", "url": "https://github.com/capsulecorp/radar/pull/2#discussion_r3"}]}
NOTE = {"author": {"__typename": "User", "login": "bulma"}, "body": "Nice Kamehameha, this reads well", "createdAt": "2026-10-22T08:00:00Z",
        "url": "https://github.com/capsulecorp/radar/pull/2#issuecomment-1"}
REPLY = {**NOTE, "author": {"__typename": "User", "login": "goku"}, "body": "Thanks, Kakarot!", "createdAt": "2026-10-22T09:30:00Z",
         "url": "https://github.com/capsulecorp/radar/pull/2#issuecomment-2"}
FILE_THREAD = {"isResolved": False, "isOutdated": False, "path": "app/models/dragon_ball.rb", "line": 1, "subjectType": "FILE",
               "comments": [{"author": {"login": "vegeta"}, "body": "Too much logic in `DragonBall`, try:\n- `DragonBall.summon`\n- a helper",
                             "createdAt": "2026-10-22T12:00:00Z", "diffHunk": "", "url": "https://github.com/capsulecorp/radar/pull/2#discussion_r4"}]}
CHANGES = {"submittedAt": "2026-10-22T09:00:00Z", "state": "CHANGES_REQUESTED", "body": "Please split this like a Fusion Dance", "author": {"login": "vegeta"}}


def light_node(pr, updated="2026-10-24T10:00:00Z", ci="SUCCESS", checks=(), after=None):
    owner_repo = pr.url.split("/")[3] + "/" + pr.url.split("/")[4]
    return {"url": pr.url, "number": pr.number, "updatedAt": updated, "title": pr.title, "headRefName": pr.head_ref_name,
            "baseRefName": "main", "headRefOid": pr.head_ref_oid, "mergeable": pr.mergeable, "author": pr.author,
            "repository": {"nameWithOwner": owner_repo},
            "head": {"nodes": [{"commit": {"statusCheckRollup": {"state": ci, "contexts": checks_page(checks, after)} if ci else None}}]}}


def checks_page(checks, after=None):
    """A page of a head commit's checks; after is the cursor of the next page, if any."""
    return {"pageInfo": {"hasNextPage": after is not None, "endCursor": after}, "nodes": list(checks)}


def pr_node(number, rollup):
    resolved = {**THREAD, "isResolved": True, "path": "app/frieza.rb"}
    bots = [{**NOTE, "author": {"__typename": "Bot", "login": "github-actions"}}, {**NOTE, "author": {"__typename": "User", "login": "deploybot"}}]
    return {"pullRequest": {
        "number": number, "title": "x", "url": f"https://github.com/capsulecorp/radar/pull/{number}", "author": {"login": "bulma"},
        "updatedAt": "2026-10-22T10:00:00Z", "headRefName": "x", "headRefOid": "h", "isDraft": False, "createdAt": "2026-10-20T10:00:00Z",
        "reviewDecision": None, "mergeable": "MERGEABLE",
        "reviewRequests": {"nodes": [{"requestedReviewer": {"__typename": "User"}}]}, "reviews": {"nodes": [CHANGES]},
        "commits": {"nodes": [{"commit": {"committedDate": "2026-10-21T10:00:00Z"}}, {"commit": {"committedDate": "2026-10-22T10:00:00Z"}}]},
        "head": {"nodes": [{"commit": {"statusCheckRollup": rollup and {"contexts": {"nodes": []}, **rollup}}}]},
        "reviewThreads": {"nodes": [{**t, "comments": {"nodes": t["comments"]}} for t in (THREAD, resolved)]},
        "comments": {"nodes": [*bots, NOTE]}}}


def ticket_view(key):
    return {"key": key, "fields": {
        "summary": "S", "issuetype": {"name": "Story"}, "priority": {"name": "Low"}, "labels": ["blocked"], "creator": {"displayName": "Goku"},
        "created": "2026-10-08T16:12:45.341+0200", "updated": "2026-10-21T17:42:10.834+0200",
        "parent": {"key": "KAME-100", "fields": {"summary": "Frieza Saga"}},
        "issuelinks": [{"type": {"inward": "is blocked by", "outward": "blocks"},
                        "inwardIssue": {"key": "KAME-2", "fields": {"summary": "Train with King Kai", "status": {"name": "En revisión"}}}}],
        "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Context"}]},
                                                   {"type": "paragraph", "content": [{"type": "text", "text": "Gather all seven dragon balls."}]}]},
        "comment": {"comments": [{"id": "10", "author": {"displayName": "Vegeta"}, "created": "2026-10-20T10:00:00.000+0200",
                                  "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Over 9000, looks good"}]}]}}]}}}
