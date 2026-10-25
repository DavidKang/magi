"""Saves a screenshot of every theme, on made-up data, to assets/screenshots/; needs rsvg-convert and a Nerd Font."""

import asyncio
import datetime as dt
import json
import os
import subprocess
import tempfile
from pathlib import Path

# A throwaway home, so the run never touches your settings or caches.
HOME = Path(tempfile.mkdtemp())
os.environ["HOME"] = str(HOME)

from tarkon.domain.entities import Epic, PullRequest, Ticket  # noqa: E402
from tarkon.tui import theme  # noqa: E402
from tarkon.tui.app import TarkonApp  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "assets" / "screenshots"
FONT = "FiraCode Nerd Font Mono"
SIZE = (180, 50)
NOW = dt.datetime.now(dt.UTC)
SETTINGS = {"team": ["alice", "bob", "carol", "dave"], "jira_project": "ACME", "github_user": "alice", "github_org": "acme",
            "jira_url": "https://acme.atlassian.net"}


def ago(days=0, hours=0):
    return (NOW - dt.timedelta(days=days, hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(repo, number, title, author, days, review="", ci="passing", mergeable="MERGEABLE", reviews=(), requests=1, draft=False):
    return PullRequest(url=f"https://github.com/acme/{repo}/pull/{number}", repo=repo, number=number, title=title, author={"login": author},
                       is_draft=draft, review_decision=review, reviews=list(reviews), review_requests=[{}] * requests,
                       created_at=ago(days), ci=ci, mergeable=mergeable, head_ref_name=f"{repo}-{number}",
                       commits=[{"committedDate": ago(hours=5)}], threads=[], conversation=[], updated_at=ago(hours=2),
                       head_ref_oid=f"{number:x}")


def approval(login, hours):
    return {"submittedAt": ago(hours=hours), "state": "APPROVED", "body": "", "author": {"login": login}}


PRS = [
    pr("storefront", 412, "[ACME-31] Show delivery dates at checkout", "bob", 1, review="APPROVED", reviews=[approval("carol", 3)], requests=0),
    pr("payments-api", 88, "[ACME-27] Retry refunds that time out", "carol", 5, ci="failing"),
    pr("ledger", 203, "[ACME-35] Export the monthly report as CSV", "dave", 2, ci="running"),
    pr("storefront", 415, "[ACME-33] Cache product images on the CDN", "bob", 0, mergeable="CONFLICTING"),
    pr("payments-api", 91, "[ACME-38] Add the Bizum payment method", "dave", 4, draft=True, requests=0),
]
MINE = [pr("ledger", 199, "[ACME-29] Reconcile payouts every hour", "alice", 3, review="APPROVED", reviews=[approval("bob", 20)],
           ci="failing", requests=0),
        pr("storefront", 418, "[ACME-36] Translate the cart into French", "alice", 1)]


def ticket(key, summary, status, column, assignee="Ana"):
    return Ticket(key=key, summary=summary, status=status, column=column, assignee=assignee)


EPICS = [Epic(key="ACME-20", summary="Faster checkout", status="Developing", owner="Ana"),
         Epic(key="ACME-21", summary="Payment methods for Spain", status="Rollout", owner="Luis")]
TICKETS = {"ACME-20": [ticket("ACME-31", "Show delivery dates at checkout", "En revisión", "review"),
                       ticket("ACME-33", "Cache product images on the CDN", "En proceso", "doing", "Luis"),
                       ticket("ACME-36", "Translate the cart into French", "En revisión", "review"),
                       ticket("ACME-30", "Measure checkout drop-off", "Finalizado", "done"),
                       ticket("ACME-40", "Remember the last address", "Tareas por hacer", "todo", "Luis")],
           "ACME-21": [ticket("ACME-27", "Retry refunds that time out", "En proceso", "doing", "Luis"),
                       ticket("ACME-38", "Add the Bizum payment method", "En proceso", "doing"),
                       ticket("ACME-26", "Split payments in three", "Ready To Deploy", "deploy"),
                       ticket("ACME-25", "Card tokens for returning buyers", "Finalizado", "done", "Luis")]}
ALL_TICKETS = [t for tickets in TICKETS.values() for t in tickets] + [ticket("ACME-29", "Reconcile payouts every hour", "En revisión", "review"),
                                                                      ticket("ACME-35", "Export the monthly report as CSV", "En proceso", "doing")]


def subject(item):
    return {"kind": "pr", "url": item.url, "ref": f"{item.repo}#{item.number}", "title": item.title}


def change(item, hours, tone, label, aside=None):
    at = (NOW - dt.timedelta(hours=hours)).astimezone().strftime("%Y-%m-%dT%H:%M")
    return {"at": at, "tone": tone, "label": label, "subject": subject(item), "note": None, "aside": aside, "item": item.url}


def board():
    return {"epics": EPICS, "tickets_by_epic": TICKETS, "by_key": {t.key: t for t in ALL_TICKETS}, "prs": PRS, "review_prs": PRS[1:3],
            "my_prs": MINE, "my_tickets": [ticket("ACME-29", "Reconcile payouts every hour", "En revisión", "review"),
                                           ticket("ACME-36", "Translate the cart into French", "En revisión", "review"),
                                           ticket("ACME-41", "Document the refund retries", "Tareas por hacer", "todo")],
            "attention": [{"subject": subject(MINE[0]), "reason": "Approved, but it has red CI."},
                          {"subject": subject(PRS[2]), "reason": "Open for review, but the ticket is still In progress. Move it to In review?"}],
            "changes": [change(PRS[0], 3, "approved", "Approved", aside="was: waiting"),
                        change(PRS[3], 6, "commented", "New PR"),
                        change(PRS[1], 9, "waiting", "New commits", aside="awaiting review"),
                        change(MINE[1], 20, "commented", "New PR")]}


async def shoot(name):
    cache = HOME / name / "cache.json"
    cache.parent.mkdir(parents=True)
    config = cache.with_name("config.json")
    config.write_text(json.dumps({**SETTINGS, "theme": name}))
    # Nothing seen yet, so the changes carry their new marks.
    cache.with_name("seen.json").write_text(json.dumps({"seen": {}}))
    app = TarkonApp(load=board, opener=print, copier=print, cache=cache, config_path=config)
    async with app.run_test(size=SIZE) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        svg = Path(app.save_screenshot(f"{name}.svg", str(HOME)))
    svg.write_text(svg.read_text().replace("Fira Code", FONT))
    subprocess.run(["rsvg-convert", "--zoom", "2", str(svg), "-o", str(OUT / f"{name}.png")], check=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in theme.THEMES:
        asyncio.run(shoot(name))
        print(OUT / f"{name}.png")


if __name__ == "__main__":
    main()
