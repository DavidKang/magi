"""Turn the fetched data into the board: attention items, changes since the last run, shared labels."""

import datetime as dt
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config
from .fetch import (column_for, days_since, fetch_children, fetch_epics, fetch_my_tickets, fetch_prs, fetch_updated,
                    parallel, run_json, search_merged_prs, search_open_prs,
                    search_review_requested_from_me, search_team_prs)

ACTIVE_COLUMNS = {"doing", "review", "deploy"}
STALE_PR_DAYS = 3
CHANGES_HOURS = 24
STATE_DIR = Path.home() / ".local" / "state" / "tarkon"
STATE_PATH = STATE_DIR / "state.json"
PR_END_LABELS = {"MERGED": ("approved", "Merged"), "CLOSED": ("draft", "Closed"), "OPEN": ("draft", "Off the board")}
NEW_PR = "New PR"
PUSHED = "New commits"
FINAL_PR_LABELS = {"Merged", "Closed"}
STATUS_TONES = {"todo": "draft", "doing": "waiting", "review": "commented", "deploy": "approved", "done": "approved"}
CI_LABELS = {"failing": ("changes", "CI red"), "running": ("commented", "CI running"),
             "passing": ("approved", "CI green"), "none": ("draft", "No CI")}


def looks_ready_but_blocked(pr):
    return review_state(pr)[0] == "approved" and (pr["ci"] == "failing" or pr["mergeable"] == "CONFLICTING")


def review_state(pr):
    if pr["isDraft"]:
        return "draft", "Draft"
    if pr["reviewDecision"] == "APPROVED":
        return "approved", "Approved"
    if pr["reviewDecision"] == "CHANGES_REQUESTED":
        return "changes", "Changes requested"
    if pr["reviews"]:
        return "commented", "Commented"
    return "waiting", "Awaiting review"


def ticket_keys_in(pr):
    return {k.upper() for k in re.findall(rf"{re.escape(config.settings.jira_project)}-\d+", f"{pr['title']} {pr['headRefName']}", flags=re.I)}


def title_keys_in(pr):
    return set(re.findall(r"\[([A-Z][A-Z0-9]+-\d+)\]", pr["title"])) | ticket_keys_in(pr)


def esc(text):
    return html.escape(str(text))


GITHUB_ICON = ('<svg class="icon github" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 0c4.42 0 8 3.58 8 8a8.013 '
               '8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2'
               '.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 '
               '2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 '
               '1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z"/></svg>')
JIRA_ICON = ('<svg class="icon jira" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M11.571 11.513H0a5.218 5.218 0 0 0 '
             '5.232 5.215h2.13v2.057A5.215 5.215 0 0 0 12.575 24V12.518a1.005 1.005 0 0 0-1.005-1.005zm5.723-5.756H5.736a5.215 5.215 0 0 0 5.215 5.214h2.129v2.058'
             'a5.218 5.218 0 0 0 5.215 5.214V6.758a1.001 1.001 0 0 0-1.001-1.001zM23.013 0H11.455a5.215 5.215 0 0 0 5.215 5.215h2.129v2.057A5.215 5.215 0 0 0 24 '
             '12.483V1.005A1.001 1.001 0 0 0 23.013 0Z"/></svg>')


def jira_link(key):
    return f'<a class="key" href="{esc(config.settings.jira_browse + key)}">{JIRA_ICON}{esc(key)}</a>'


def github_link(url, text, tooltip=""):
    title = f' title="{esc(tooltip)}"' if tooltip else ""
    linked, rest = re.fullmatch(r"(\[[^\]]+\])?\s*(.*)", text).groups()
    if not linked:
        linked, rest = text, ""
    return f'<a href="{esc(url)}"{title}>{GITHUB_ICON}{esc(linked)}</a>' + (f" {esc(rest)}" if rest else "")


def pr_titled(pr):
    return github_link(pr["url"], pr["title"], f'{pr["repo"]}#{pr["number"]}')


def ticket_titled(ticket):
    return f'{jira_link(ticket["key"])} {esc(ticket["summary"])}'


def attention_items(all_tickets, prs, merged_by_ticket):
    items = []
    for t in all_tickets:
        open_for_review = [pr for pr in t["prs"] if not pr["isDraft"]]
        if t["column"] == "doing":
            for pr in open_for_review:
                items.append((pr_titled(pr), "Open for review, but the ticket is still In progress. Move it to In review?"))
        if t["column"] in {"doing", "review"} and not t["prs"]:
            for merged in merged_by_ticket.get(t["key"], []):
                items.append((merged, f'Merged, but the ticket is still {esc(t["status"])} with no other open PR. Move it?'))
        if t["column"] == "review" and not t["prs"] and not merged_by_ticket.get(t["key"]):
            items.append((ticket_titled(t), "In review with no open PR."))
        if t["column"] == "done":
            for pr in t["prs"]:
                items.append((pr_titled(pr), "Still open, but the ticket is already done."))
        if t["column"] in ACTIVE_COLUMNS and t["assignee"] == "Unassigned":
            items.append((ticket_titled(t), "Active with no owner."))
    for pr in prs:
        if looks_ready_but_blocked(pr):
            reason = "red CI" if pr["ci"] == "failing" else "conflicts"
            items.append((pr_titled(pr), f"Approved, but it has {reason}."))
        if review_state(pr)[0] == "waiting" and days_since(pr["createdAt"]) > STALE_PR_DAYS:
            items.append((pr_titled(pr), f'{days_since(pr["createdAt"])} days without any review.'))
    return items


def snapshot(epics, tickets_by_epic, prs):
    return {"epics": {e["key"]: {"summary": e["summary"], "tickets": [t["key"] for t in tickets_by_epic[e["key"]]]} for e in epics},
            "tickets": {t["key"]: t["status"] for tickets in tickets_by_epic.values() for t in tickets},
            "prs": {pr["url"]: {"label": f'{pr["repo"]}#{pr["number"]}', "title": pr["title"],
                                "review": list(review_state(pr)), "ci": list(CI_LABELS[pr["ci"]]),
                                "head": pr["headRefOid"], "reviews": len(pr["reviews"]),
                                "awaiting": bool(pr["reviewRequests"]), "tickets": sorted(ticket_keys_in(pr))} for pr in prs}}


def change(item, tone, label, text):
    return {"item": item, "tone": tone, "label": label, "text": text}


def changes_between(before, now, summaries):
    found = []
    before_epics = before.get("epics", now["epics"])
    new_epics = [key for key in now["epics"] if key not in before_epics]
    gone_epics = [key for key in before_epics if key not in now["epics"]]
    quiet = ({t for key in new_epics for t in now["epics"][key]["tickets"]}
             | {t for key in gone_epics for t in before_epics[key]["tickets"]})
    for key in new_epics:
        found.append(change(f"{config.settings.jira_browse}{key}", "commented", "New epic",
                            f'{jira_link(key)} {esc(now["epics"][key]["summary"])}'))
    for key in gone_epics:
        found.append(change(f"{config.settings.jira_browse}{key}", "draft", "Off the epics",
                            f'{jira_link(key)} {esc(before_epics[key]["summary"])}'))
    for key, status in now["tickets"].items():
        tone = STATUS_TONES[column_for(status)]
        ticket = f"{jira_link(key)} {esc(summaries[key])}"
        if key in quiet:
            continue
        if key not in before["tickets"]:
            found.append(change(f"{config.settings.jira_browse}{key}", tone, status, f"{ticket} joins the epics"))
        elif before["tickets"][key] != status:
            found.append(change(f"{config.settings.jira_browse}{key}", tone, status, f'{ticket} <span class="age">was: {esc(before["tickets"][key])}</span>'))
    for key in before["tickets"].keys() - now["tickets"].keys() - quiet:
        found.append(change(f"{config.settings.jira_browse}{key}", "draft", "Off the epics", f"{jira_link(key)} (cancelled or moved)"))
    for url, pr in now["prs"].items():
        link = github_link(url, pr["title"], pr["label"])
        old = before["prs"].get(url)
        if not old:
            if not (pr["tickets"] and quiet.issuperset(pr["tickets"])):
                found.append(change(url, "commented", NEW_PR, link))
            continue
        if old["review"] != pr["review"]:
            found.append(change(url, *pr["review"], f'{link} <span class="age">was: {esc(old["review"][1])}</span>'))
        elif pr["reviews"] > old.get("reviews", pr["reviews"]):
            found.append(change(url, *pr["review"], f'{link} <span class="age">new review</span>'))
        if old.get("head", pr["head"]) != pr["head"]:
            waiting = ' <span class="age">awaiting review</span>' if pr["awaiting"] else ""
            found.append(change(url, "waiting", PUSHED, f"{link}{waiting}"))
    for url in before["prs"].keys() - now["prs"].keys():
        pr = before["prs"][url]
        if pr.get("tickets") and quiet.issuperset(pr["tickets"]):
            continue
        state = run_json(["gh", "pr", "view", url, "--json", "state"])["state"]
        found.append(change(url, *PR_END_LABELS[state], github_link(url, pr["title"], pr["label"])))
    return found


def recent_changes(state, now, summaries, stamp):
    if state is None:
        return None
    cutoff = stamp - dt.timedelta(hours=CHANGES_HOURS)
    fresh = [{"at": stamp.isoformat(timespec="minutes"), **c} for c in changes_between(state["snapshot"], now, summaries)]
    return latest_per_item(fresh + [c for c in state["changes"] if dt.datetime.fromisoformat(c["at"]) >= cutoff])


def latest_per_item(changes):
    kept = {}
    for c in changes:
        if c["item"] not in kept:
            kept[c["item"]] = c
        elif c["label"] == NEW_PR and kept[c["item"]]["label"] not in FINAL_PR_LABELS:
            kept[c["item"]] = {**c, "at": kept[c["item"]]["at"]}
    return list(kept.values())


TUI_REVIEW = {"approved": "ok", "changes": "bad", "waiting": "warn", "commented": "blue", "draft": "dim"}
TUI_CI = {"passing": ("ok", "✓ ci"), "failing": ("bad", "✗ ci"), "running": ("warn", "… ci"), "none": ("dim", "– ci")}
TUI_REVIEW_EVENTS = {"APPROVED": "ok", "CHANGES_REQUESTED": "bad"}
TUI_REPO_ALIASES = {}


def tui_repo(pr):
    return TUI_REPO_ALIASES.get(pr["repo"], pr["repo"])


def plain(markup):
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


def local_time(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%b %d %H:%M")


def save_state(snapshot, changes):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Written aside and renamed, so quitting mid-write never leaves a truncated state.
    staged = STATE_PATH.with_suffix(".tmp")
    staged.write_text(json.dumps({"snapshot": snapshot, "changes": changes}, ensure_ascii=False, indent=1))
    staged.replace(STATE_PATH)


def collect():
    pool = ThreadPoolExecutor(max_workers=8)
    team_prs = pool.submit(search_team_prs)
    review_requested = pool.submit(search_review_requested_from_me)
    my_tickets = pool.submit(fetch_my_tickets)
    epics = fetch_epics()
    epic_keys = [epic["key"] for epic in epics]
    tickets_by_epic = dict(zip(epic_keys, parallel(fetch_children, epic_keys)))
    by_key = {t["key"]: t for ts in tickets_by_epic.values() for t in ts}

    updated = pool.submit(parallel, fetch_updated, [t for t in by_key.values() if t["column"] in ACTIVE_COLUMNS])
    search_keys = epic_keys + [k for k, t in by_key.items() if t["column"] != "done"]
    active_keys = [k for k, t in by_key.items() if t["column"] in {"doing", "review"}]
    merged_prs = pool.submit(search_merged_prs, active_keys)
    prs = []
    candidates = search_open_prs(search_keys) | team_prs.result()
    for pr in fetch_prs(candidates.values()):
        linked = [k for k in ticket_keys_in(pr) if k in by_key]
        if not linked and pr["author"]["login"] not in config.settings.team:
            continue
        prs.append(pr)
        for k in linked:
            by_key[k]["prs"].append(pr)

    merged_by_ticket = {}
    for merged in merged_prs.result():
        label = github_link(merged["url"], merged["title"], f'{merged["repository"]["name"]}#{merged["number"]}')
        for k in ticket_keys_in({"title": merged["title"], "headRefName": ""}):
            if k in active_keys:
                merged_by_ticket.setdefault(k, []).append(label)

    known = {pr["url"]: pr for pr in prs}
    requested = review_requested.result()
    missing = [url for url in requested if url not in known]
    fetched = dict(zip(missing, fetch_prs(requested[url] for url in missing)))
    review_prs = [known.get(url) or fetched[url] for url in requested]
    my_tickets = my_tickets.result()
    updated.result()

    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else None
    now = snapshot(epics, tickets_by_epic, {pr["url"]: pr for pr in prs + review_prs}.values())
    stamp = dt.datetime.now()
    changes = recent_changes(state, now, {k: t["summary"] for k, t in by_key.items()}, stamp)

    save_state(now, changes or [])
    pool.shutdown()
    return {"epics": epics, "tickets_by_epic": tickets_by_epic, "by_key": by_key, "prs": prs, "review_prs": review_prs,
            "my_prs": [pr for pr in prs if pr["author"]["login"] == config.settings.github_user], "my_tickets": my_tickets,
            "attention": attention_items(list(by_key.values()), prs, merged_by_ticket), "changes": changes or [],
            "merged_by_ticket": merged_by_ticket, "now": now}
