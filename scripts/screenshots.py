"""Saves a screenshot of every theme, on made-up data, to assets/screenshots/.

Each theme opens in its own Ghostty window, which closes by itself. Needs Ghostty, a Nerd Font, and Screen Recording
permission for the terminal that runs this script.
"""

import asyncio
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# A throwaway home, so the run never touches your settings or caches; the tools it calls keep the real one.
REAL_ENV = dict(os.environ)
HOME = Path(tempfile.mkdtemp())
os.environ["HOME"] = str(HOME)

from magi.domain.entities import Epic, PullRequest, Ticket  # noqa: E402
from magi.tui import theme  # noqa: E402
from magi.tui.app import MagiApp  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "assets" / "screenshots"
FONT = "FiraCode Nerd Font Mono"
SIZE = (180, 50)
RENDER_SECONDS = 4
HOLD_SECONDS = 8
# CoreGraphics lists every window with its owner's pid; screencapture -l takes the id.
WINDOW_ID = """
import CoreGraphics
let pid = Int(CommandLine.arguments[1])!
let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as! [[String: Any]]
for w in windows where (w[kCGWindowOwnerPID as String] as? Int) == pid && (w[kCGWindowLayer as String] as? Int) == 0 {
    print(w[kCGWindowNumber as String]!)
}
"""
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


def run(name):
    """Shows the board in this terminal with the made-up data, for a few seconds."""
    cache = HOME / "cache.json"
    config = cache.with_name("config.json")
    config.write_text(json.dumps({**SETTINGS, "theme": name}))

    async def hold(pilot):
        await asyncio.sleep(HOLD_SECONDS)
        pilot.app.exit()

    MagiApp(load=board, opener=print, copier=print, cache=cache, config_path=config).run(auto_pilot=hold)


def window(pid):
    """The id of the window a process shows, once it shows one."""
    for _ in range(20):
        found = subprocess.run(["swift", "-e", WINDOW_ID, str(pid)], capture_output=True, text=True, env=REAL_ENV).stdout.split()
        if found:
            return found[0]
        time.sleep(0.5)
    raise SystemExit(f"Ghostty (pid {pid}) never showed a window")


def shoot(name):
    command = f"{sys.executable} {Path(__file__).resolve()} --run {name}"
    subprocess.run(["open", "-na", "Ghostty.app", "--args", "--title=Magi", f"--window-width={SIZE[0]}",
                    f"--window-height={SIZE[1]}", f"--font-family={FONT}", "--font-size=13", "--window-save-state=never",
                    "--confirm-close-surface=false", "--quit-after-last-window-closed=true",
                    f"--command={command}"], check=True)
    time.sleep(1)
    pid = subprocess.run(["pgrep", "-n", "-f", f"MacOS/ghostty.*--run {name}"], capture_output=True, text=True, check=True).stdout.strip()
    window_id = window(pid)
    time.sleep(RENDER_SECONDS)
    subprocess.run(["screencapture", "-o", "-x", "-l", window_id, str(OUT / f"{name}.png")], check=True)
    while subprocess.run(["pgrep", "-f", f"MacOS/ghostty.*--run {name}"], capture_output=True).returncode == 0:
        time.sleep(0.5)


def main():
    if sys.argv[1:2] == ["--run"]:
        return run(sys.argv[2])
    OUT.mkdir(parents=True, exist_ok=True)
    for name in theme.THEMES:
        shoot(name)
        print(OUT / f"{name}.png")


if __name__ == "__main__":
    main()
