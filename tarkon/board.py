"""Turn the fetched data into the board: attention items and changes since the last run, as plain data the views render."""

import dataclasses
import datetime as dt
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import storage
from .entities import Epic, PullRequest, TicketDetail, ticket_from
from .fetch import days_since, parallel
from .github import fetch_pr_states, fetch_prs, search_prs, search_terms
from .jira import changed_since, column_for, fetch_children, fetch_epics, fetch_my_tickets, fetch_ticket_detail, fetch_updated

ACTIVE_COLUMNS = {"doing", "review", "deploy"}
STALE_PR_DAYS = 3
CHANGES_HOURS = 24
STATE_DIR = Path.home() / ".local" / "state" / "tarkon"
STATE_PATH = STATE_DIR / "state.json"
PR_CACHE_PATH = Path.home() / ".cache" / "tarkon" / "prs.json"
UPDATED_CACHE_PATH = Path.home() / ".cache" / "tarkon" / "updated.json"
MY_TICKETS_CACHE_PATH = Path.home() / ".cache" / "tarkon" / "my-tickets.json"
# Minutes added to the time since the last refresh when asking Jira what changed, for clock skew and slow refreshes.
JIRA_MARGIN_MINUTES = 5
OPEN_PRS = "is:pr is:open archived:false"
PR_END_LABELS = {"MERGED": ("approved", "Merged"), "CLOSED": ("draft", "Closed"), "OPEN": ("draft", "Off the board")}
NEW_PR = "New PR"
PUSHED = "New commits"
FINAL_PR_LABELS = {"Merged", "Closed"}
STATUS_TONES = {"todo": "draft", "doing": "waiting", "review": "commented", "deploy": "approved", "done": "approved"}
CI_LABELS = {"failing": ("changes", "CI red"), "running": ("commented", "CI running"),
             "passing": ("approved", "CI green"), "none": ("draft", "No CI")}


def looks_ready_but_blocked(pr):
    return review_state(pr)[0] == "approved" and (pr.ci == "failing" or pr.mergeable == "CONFLICTING")


def review_state(pr):
    if pr.is_draft:
        return "draft", "Draft"
    if pr.review_decision == "APPROVED":
        return "approved", "Approved"
    if pr.review_decision == "CHANGES_REQUESTED":
        return "changes", "Changes requested"
    if pr.reviews:
        return "commented", "Commented"
    return "waiting", "Awaiting review"


def ticket_keys_in(pr, project):
    return {k.upper() for k in re.findall(rf"{re.escape(project)}-\d+", f"{pr.title} {pr.head_ref_name}", flags=re.I)}


def title_keys_in(pr, project):
    return set(re.findall(r"\[([A-Z][A-Z0-9]+-\d+)\]", pr.title)) | ticket_keys_in(pr, project)


def pr_subject(url, ref, title):
    return {"kind": "pr", "url": url, "ref": ref, "title": title}


def ticket_subject(key, browse, title=None):
    return {"kind": "ticket", "url": browse + key, "ref": key, "title": title}


def title_parts(title):
    # A leading [KEY] is the linked part of a PR title; the rest follows it after one space.
    linked, rest = re.fullmatch(r"(\[[^\]]+\])?\s*(.*)", title).groups()
    return (linked, rest) if linked else (title, "")


def subject_text(subject):
    if subject["kind"] == "pr":
        return " ".join(part for part in title_parts(subject["title"]) if part)
    return " ".join(part for part in (subject["ref"], subject["title"]) if part)


def change_text(change):
    return " ".join(part for part in (subject_text(change["subject"]), change["note"], change["aside"]) if part)


def attention_items(all_tickets, prs, merged_by_ticket, settings):
    items = []

    def flag(subject, reason):
        items.append({"subject": subject, "reason": reason})
    for t in all_tickets:
        open_for_review = [pr for pr in t.prs if not pr.is_draft]
        if t.column == "doing":
            for pr in open_for_review:
                flag(pr_subject(pr.url, f"{pr.repo}#{pr.number}", pr.title), "Open for review, but the ticket is still In progress. Move it to In review?")
        if t.column in {"doing", "review"} and not t.prs:
            for merged in merged_by_ticket.get(t.key, []):
                flag(merged, f"Merged, but the ticket is still {t.status} with no other open PR. Move it?")
        if t.column == "review" and not t.prs and not merged_by_ticket.get(t.key):
            flag(ticket_subject(t.key, settings.jira_browse, t.summary), "In review with no open PR.")
        if t.column == "done":
            for pr in t.prs:
                flag(pr_subject(pr.url, f"{pr.repo}#{pr.number}", pr.title), "Still open, but the ticket is already done.")
        if t.column in ACTIVE_COLUMNS and t.assignee == "Unassigned":
            flag(ticket_subject(t.key, settings.jira_browse, t.summary), "Active with no owner.")
    for pr in prs:
        subject = pr_subject(pr.url, f"{pr.repo}#{pr.number}", pr.title)
        if looks_ready_but_blocked(pr):
            reason = "red CI" if pr.ci == "failing" else "conflicts"
            flag(subject, f"Approved, but it has {reason}.")
        if review_state(pr)[0] == "waiting" and days_since(pr.created_at) > STALE_PR_DAYS:
            flag(subject, f"{days_since(pr.created_at)} days without any review.")
    return items


def snapshot(epics, tickets_by_epic, prs, settings):
    return {"epics": {e.key: {"summary": e.summary, "tickets": [t.key for t in tickets_by_epic[e.key]]} for e in epics},
            "tickets": {t.key: t.status for tickets in tickets_by_epic.values() for t in tickets},
            "prs": {pr.url: {"label": f"{pr.repo}#{pr.number}", "title": pr.title,
                             "review": list(review_state(pr)), "ci": list(CI_LABELS[pr.ci]),
                             "head": pr.head_ref_oid, "reviews": len(pr.reviews),
                             "awaiting": bool(pr.review_requests), "tickets": sorted(ticket_keys_in(pr, settings.jira_project))} for pr in prs}}


def change(subject, tone, label, note=None, aside=None):
    return {"item": subject["url"], "tone": tone, "label": label, "subject": subject, "note": note, "aside": aside}


def quiet_tickets(before, now):
    # Tickets of an epic that joined or left the board: the epic change already covers them.
    before_epics = before.get("epics", now["epics"])
    return ({t for key in now["epics"].keys() - before_epics.keys() for t in now["epics"][key]["tickets"]}
            | {t for key in before_epics.keys() - now["epics"].keys() for t in before_epics[key]["tickets"]})


def vanished_prs(before, now):
    quiet = quiet_tickets(before, now)
    return [url for url in before["prs"].keys() - now["prs"].keys()
            if not (before["prs"][url].get("tickets") and quiet.issuperset(before["prs"][url]["tickets"]))]


def changes_between(before, now, summaries, ended, settings):
    found = []
    before_epics = before.get("epics", now["epics"])
    new_epics = [key for key in now["epics"] if key not in before_epics]
    gone_epics = [key for key in before_epics if key not in now["epics"]]
    quiet = quiet_tickets(before, now)
    for key in new_epics:
        found.append(change(ticket_subject(key, settings.jira_browse, now["epics"][key]["summary"]), "commented", "New epic"))
    for key in gone_epics:
        found.append(change(ticket_subject(key, settings.jira_browse, before_epics[key]["summary"]), "draft", "Off the epics"))
    for key, status in now["tickets"].items():
        tone = STATUS_TONES[column_for(status)]
        ticket = ticket_subject(key, settings.jira_browse, summaries[key])
        if key in quiet:
            continue
        if key not in before["tickets"]:
            found.append(change(ticket, tone, status, note="joins the epics"))
        elif before["tickets"][key] != status:
            found.append(change(ticket, tone, status, aside=f'was: {before["tickets"][key]}'))
    for key in before["tickets"].keys() - now["tickets"].keys() - quiet:
        found.append(change(ticket_subject(key, settings.jira_browse), "draft", "Off the epics", note="(cancelled or moved)"))
    for url, pr in now["prs"].items():
        subject = pr_subject(url, pr["label"], pr["title"])
        old = before["prs"].get(url)
        if not old:
            if not (pr["tickets"] and quiet.issuperset(pr["tickets"])):
                found.append(change(subject, "commented", NEW_PR))
            continue
        if old["review"] != pr["review"]:
            found.append(change(subject, *pr["review"], aside=f'was: {old["review"][1]}'))
        elif pr["reviews"] > old.get("reviews", pr["reviews"]):
            found.append(change(subject, *pr["review"], aside="new review"))
        if old.get("head", pr["head"]) != pr["head"]:
            found.append(change(subject, "waiting", PUSHED, aside="awaiting review" if pr["awaiting"] else None))
    for url in vanished_prs(before, now):
        pr = before["prs"][url]
        found.append(change(pr_subject(url, pr["label"], pr["title"]), *PR_END_LABELS[ended[url]]))
    return found


def recent_changes(state, now, summaries, stamp, ended, settings):
    if state is None:
        return None
    cutoff = stamp - dt.timedelta(hours=CHANGES_HOURS)
    fresh = [{"at": stamp.isoformat(timespec="minutes"), **c} for c in changes_between(state["snapshot"], now, summaries, ended, settings)]
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
    return TUI_REPO_ALIASES.get(pr.repo, pr.repo)


def local_time(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%b %d %H:%M")


def save_state(snapshot, changes):
    storage.write(STATE_PATH, {"snapshot": snapshot, "changes": changes})


def pr_details(found):
    """Full PRs for the light ones a search found: fetched again only when a PR changed since the last refresh."""
    cached = {url: PullRequest(**pr) for url, pr in (storage.read(PR_CACHE_PATH) or {}).get("prs", {}).items()}
    stale = [pr for pr in found if pr.url not in cached or cached[pr.url].updated_at != pr.updated_at]
    fresh = dict(zip((pr.url for pr in stale), fetch_prs((pr.name_with_owner, pr.number) for pr in stale)))
    details = {pr.url: fresh.get(pr.url) or cached[pr.url] for pr in found}
    storage.write(PR_CACHE_PATH, {"prs": details})
    # CI and mergeability change without touching updatedAt, so they always come from the search.
    return {pr.url: dataclasses.replace(details[pr.url], ci=pr.ci, mergeable=pr.mergeable) for pr in found}


def refetch_changed(path, keys, fetch_one, started, linked=None, rebuild=None):
    """fetch_one(key) for the keys Jira changed since the last refresh, or never seen; the rest come from path.

    linked(found) names the tickets a cached value shows, so a change to one of them fetches the value again;
    rebuild(value) turns a value read back from path into what fetch_one returns.
    """
    cache = storage.read(path)
    found = {key: rebuild(value) if rebuild else value for key, value in cache["found"].items()} if cache else {}
    known = [key for key in keys if key in found]
    changed = set()
    if known:
        minutes = math.ceil((time.time() - cache["at"]) / 60) + JIRA_MARGIN_MINUTES
        changed = changed_since(known, minutes, known if linked else ())
    stale = [key for key in keys if key not in found or key in changed or (linked and changed & set(linked(found[key])))]
    found = {**{key: found[key] for key in keys if key in found}, **dict(zip(stale, parallel(fetch_one, stale)))}
    storage.write(path, {"at": started, "found": found})
    return found


def collect(settings):
    started = time.time()
    pool = ThreadPoolExecutor(max_workers=8)
    org = f"org:{settings.github_org}"
    authors = [settings.team[start:start + 6] for start in range(0, len(settings.team), 6)]
    team_prs = pool.submit(parallel, search_prs, [f"{OPEN_PRS} {org} " + " ".join(f"author:{a}" for a in chunk) for chunk in authors])
    review_requested = pool.submit(search_prs, f"{OPEN_PRS} {org} user-review-requested:@me")
    my_tickets = pool.submit(fetch_my_tickets, lambda keys: refetch_changed(MY_TICKETS_CACHE_PATH, keys, fetch_ticket_detail, started,
                                                                            lambda detail: [link["key"] for link in detail.links],
                                                                            lambda value: TicketDetail(**value)))
    epics = fetch_epics(settings)
    epic_keys = [epic.key for epic in epics]
    tickets_by_epic = dict(zip(epic_keys, parallel(fetch_children, epic_keys)))
    by_key = {t.key: t for ts in tickets_by_epic.values() for t in ts}

    active = [t for t in by_key.values() if t.column in ACTIVE_COLUMNS]
    updated = pool.submit(refetch_changed, UPDATED_CACHE_PATH, [t.key for t in active], fetch_updated, started)
    search_keys = epic_keys + [k for k, t in by_key.items() if t.column != "done"]
    active_keys = [k for k, t in by_key.items() if t.column in {"doing", "review"}]
    merged_prs = pool.submit(parallel, search_prs, [f"is:pr is:merged {org} {' '.join(terms)}" for terms in search_terms(active_keys)])
    open_prs = parallel(search_prs, [f"{OPEN_PRS} {org} {' '.join(terms)}" for terms in search_terms(search_keys)])
    candidates = {pr.url: pr for found in open_prs + team_prs.result() for pr in found}
    shown = [pr for pr in candidates.values()
             if any(k in by_key for k in ticket_keys_in(pr, settings.jira_project)) or pr.author["login"] in settings.team]
    requested = review_requested.result()
    detailed = pr_details(list({pr.url: pr for pr in shown + requested}.values()))
    prs = [detailed[pr.url] for pr in shown]
    for pr in prs:
        for k in ticket_keys_in(pr, settings.jira_project):
            if k in by_key:
                by_key[k].prs.append(pr)
    review_prs = [detailed[pr.url] for pr in requested]

    merged_by_ticket = {}
    for merged in (pr for found in merged_prs.result() for pr in found):
        subject = pr_subject(merged.url, f"{merged.repo}#{merged.number}", merged.title)
        for k in ticket_keys_in(dataclasses.replace(merged, head_ref_name=""), settings.jira_project):
            if k in active_keys:
                merged_by_ticket.setdefault(k, []).append(subject)
    my_tickets = my_tickets.result()
    found_updated = updated.result()
    for ticket in active:
        ticket.updated = found_updated[ticket.key]

    state = storage.read(STATE_PATH)
    now = snapshot(epics, tickets_by_epic, {pr.url: pr for pr in prs + review_prs}.values(), settings)
    stamp = dt.datetime.now()
    ended = fetch_pr_states(vanished_prs(state["snapshot"], now) if state else [])
    changes = recent_changes(state, now, {k: t.summary for k, t in by_key.items()}, stamp, ended, settings)

    save_state(now, changes or [])
    pool.shutdown()
    return {"epics": epics, "tickets_by_epic": tickets_by_epic, "by_key": by_key, "prs": prs, "review_prs": review_prs,
            "my_prs": [pr for pr in prs if pr.author["login"] == settings.github_user], "my_tickets": my_tickets,
            "attention": attention_items(list(by_key.values()), prs, merged_by_ticket, settings), "changes": changes or [],
            "merged_by_ticket": merged_by_ticket, "now": now}


def saved_board(data):
    """A board collect returned, read back from json: its epics, tickets and PRs rebuilt as entities."""
    tickets_by_epic = {key: [ticket_from(t) for t in tickets] for key, tickets in data["tickets_by_epic"].items()}
    return {**data, "epics": [Epic(**e) for e in data["epics"]], "tickets_by_epic": tickets_by_epic,
            "by_key": {t.key: t for tickets in tickets_by_epic.values() for t in tickets},
            "prs": [PullRequest(**pr) for pr in data["prs"]], "review_prs": [PullRequest(**pr) for pr in data["review_prs"]],
            "my_prs": [PullRequest(**pr) for pr in data["my_prs"]], "my_tickets": [ticket_from(t) for t in data["my_tickets"]]}
