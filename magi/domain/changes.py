"""What changed on the board since the last run: snapshots of it, and the changes between two of them."""

import datetime as dt

from .keys import ticket_keys_in, title_parts
from .review import CI_LABELS, review_state
from .status import column_for, status_label

CHANGES_HOURS = 24
PR_END_LABELS = {"MERGED": ("approved", "Merged"), "CLOSED": ("draft", "Closed"), "OPEN": ("draft", "Off the board")}
NEW_PR = "New PR"
PUSHED = "New commits"
FINAL_PR_LABELS = {"Merged", "Closed"}
STATUS_TONES = {"todo": "draft", "doing": "waiting", "review": "commented", "deploy": "approved", "done": "approved"}


def pr_subject(url, ref, title):
    return {"kind": "pr", "url": url, "ref": ref, "title": title}


def ticket_subject(key, browse, title=None):
    return {"kind": "ticket", "url": browse + key, "ref": key, "title": title}


def subject_text(subject):
    if subject["kind"] == "pr":
        return " ".join(part for part in title_parts(subject["title"]) if part)
    return " ".join(part for part in (subject["ref"], subject["title"]) if part)


def change_text(change):
    return " ".join(part for part in (subject_text(change["subject"]), change["note"], change["aside"]) if part)


def snapshot(epics, tickets_by_epic, prs, settings):
    return {"epics": {e.key: {"summary": e.summary, "tickets": [t.key for t in tickets_by_epic[e.key]]} for e in epics},
            "tickets": {t.key: t.status for tickets in tickets_by_epic.values() for t in tickets},
            "prs": {pr.url: {"label": f"{pr.repo}#{pr.number}", "title": pr.title,
                             "review": list(review_state(pr)), "ci": list(CI_LABELS[pr.ci]),
                             "head": pr.head_ref_oid, "pushed": max((c["committedDate"] for c in pr.commits), default=""),
                             "reviews": sum(1 for r in pr.reviews if r["submittedAt"]),
                             "awaiting": bool(pr.review_requests), "tickets": sorted(ticket_keys_in(pr, settings.jira_project))} for pr in prs}}


def snapshot_epics(taken):
    return list(taken["epics"])


def change(subject, tone, label, note=None, aside=None, group=None, told=False):
    """told: a commit or a new review caused it, so the PR's own history already tells it."""
    return {"item": subject["url"], "group": group or subject["url"], "tone": tone, "label": label, "subject": subject,
            "note": note, "aside": aside, "told": told}


def ticket_groups(before, now):
    """The PR a ticket's changes join: the only one on the board, before or now, that names the ticket."""
    named = {}
    for url, pr in {**before["prs"], **now["prs"]}.items():
        for key in pr.get("tickets", []):
            named.setdefault(key, set()).add(url)
    return {key: urls.pop() for key, urls in named.items() if len(urls) == 1}


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
    groups = ticket_groups(before, now)
    for key in new_epics:
        found.append(change(ticket_subject(key, settings.jira_browse, now["epics"][key]["summary"]), "commented", "New epic"))
    for key in gone_epics:
        found.append(change(ticket_subject(key, settings.jira_browse, before_epics[key]["summary"]), "draft", "Off the epics"))
    for url, pr in now["prs"].items():
        subject = pr_subject(url, pr["label"], pr["title"])
        old = before["prs"].get(url)
        if not old:
            if not (pr["tickets"] and quiet.issuperset(pr["tickets"])):
                found.append(change(subject, "commented", NEW_PR))
            continue
        reviewed = pr["reviews"] > old.get("reviews", pr["reviews"])
        if old["review"] != pr["review"]:
            found.append(change(subject, *pr["review"], aside=f'was: {old["review"][1]}', told=reviewed))
        elif reviewed:
            found.append(change(subject, *pr["review"], aside="new review", told=True))
        if old.get("head", pr["head"]) != pr["head"]:
            found.append(change(subject, "waiting", PUSHED, aside="awaiting review" if pr["awaiting"] else None,
                                told=pr["pushed"] > old.get("pushed", "")))
    for url in vanished_prs(before, now):
        pr = before["prs"][url]
        found.append(change(pr_subject(url, pr["label"], pr["title"]), *PR_END_LABELS[ended[url]]))
    # After the PRs: a refresh stamps its changes alike, so a PR's own change leads its ticket's move.
    for key, status in now["tickets"].items():
        tone = STATUS_TONES[column_for(status)]
        ticket = ticket_subject(key, settings.jira_browse, summaries[key])
        if key in quiet:
            continue
        if key not in before["tickets"]:
            found.append(change(ticket, tone, status_label(status), note="joins the epics", group=groups.get(key)))
        elif before["tickets"][key] != status:
            found.append(change(ticket, tone, status_label(status), aside=f'was: {status_label(before["tickets"][key])}',
                                group=groups.get(key)))
    for key in before["tickets"].keys() - now["tickets"].keys() - quiet:
        found.append(change(ticket_subject(key, settings.jira_browse), "draft", "Off the epics", note="(cancelled or moved)",
                            group=groups.get(key)))
    return found


def recent_changes(state, now, summaries, stamp, ended, settings):
    if state is None:
        return None
    cutoff = stamp - dt.timedelta(hours=CHANGES_HOURS)
    fresh = [{"at": stamp.isoformat(timespec="minutes"), **c} for c in changes_between(state["snapshot"], now, summaries, ended, settings)]
    return regrouped(fresh + [c for c in state["changes"] if dt.datetime.fromisoformat(c["at"]) >= cutoff])


def regrouped(changes):
    """Changes newest first, each item's joined to the group its newest change joined, so a ticket shows once."""
    groups = {}
    for c in changes:
        groups.setdefault(c["item"], c["group"])
    return [{**c, "group": groups[c["item"]]} for c in changes]


def latest(changes, by):
    """The newest change of each item or group, from changes newest first; a PR new in the window stays a new PR."""
    kept = {}
    for c in changes:
        newer = kept.get(c[by])
        if not newer:
            kept[c[by]] = c
        elif c["label"] == NEW_PR and newer["item"] == c["item"] and newer["label"] not in FINAL_PR_LABELS:
            kept[c[by]] = {**c, "at": newer["at"]}
    return list(kept.values())


def group_changes(changes, group, histories):
    """The changes of a group that its PR's own history does not already tell."""
    return [c for c in changes if c["group"] == group and not (group in histories and c["told"])]

