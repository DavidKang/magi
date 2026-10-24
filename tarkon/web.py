"""Render the board as an html page, the browser version of Tarkon."""

import base64
import datetime as dt
import re
import sys
from pathlib import Path

from . import config
from .board import (CHANGES_HOURS, CI_LABELS, STATE_DIR, TUI_CI, TUI_REVIEW, TUI_REVIEW_EVENTS, attention_items,
                    collect, esc, github_link, jira_link, local_time, plain, pr_titled, review_state,
                    ticket_keys_in, title_keys_in, tui_repo)
from .fetch import COLUMNS, days_since

URGENT_PR_DAYS = 3
LOGO = "data:image/png;base64," + base64.b64encode(Path(__file__).with_name("logo.png").read_bytes()).decode()
def ci_pills(pr):
    tone, label = CI_LABELS[pr["ci"]]
    conflict = ' <span class="pill changes">Conflicts</span>' if pr["mergeable"] == "CONFLICTING" else ""
    return f'<span class="pill {tone}">{label}</span>{conflict}'


def pr_chip(pr):
    state, label = review_state(pr)
    return (f'<a class="pr {state}" href="{esc(pr["url"])}" title="{esc(pr["title"])}">'
            f'{esc(pr["repo"])}#{pr["number"]} · {label}</a>')


def card(ticket):
    age = f'updated {days_since(ticket["updated"])} d ago' if ticket["updated"] else ""
    prs = "".join(pr_chip(pr) for pr in ticket["prs"])
    return (f'<li class="card"><div class="card-top">{jira_link(ticket["key"])}'
            f'<span class="age">{age}</span></div>'
            f'<div class="card-title">{esc(ticket["summary"])}</div>'
            f'<div class="card-who">{esc(ticket["assignee"])}</div>'
            f'{f"<div class=prs>{prs}</div>" if prs else ""}</li>')


def board(epic, tickets):
    counts = {key: sum(1 for t in tickets if t["column"] == key) for key, _, _ in COLUMNS}
    total = len(tickets)
    done_pct = round(100 * counts["done"] / total) if total else 0
    columns = []
    for key, label, _ in COLUMNS:
        cards = [t for t in tickets if t["column"] == key]
        body = "".join(card(t) for t in cards)
        if key == "done" and cards:
            body = f'<details><summary>Show {len(cards)}</summary><ul class="cards">{body}</ul></details>'
        elif cards:
            body = f'<ul class="cards">{body}</ul>'
        else:
            body = '<p class="empty">—</p>'
        columns.append(f'<div class="col col-{key}"><h4>{label} <span class="count">{counts[key]}</span></h4>{body}</div>')
    lanes = "".join(f'<span>{label} <span class="count">{counts[key]}</span></span>' for key, label, _ in COLUMNS)
    return (f'<section class="epic" id="{epic["key"]}"><details class="epic-toggle"><summary class="epic-head">'
            f'<div>{jira_link(epic["key"])}<h3>{esc(epic["summary"])}</h3>'
            f'<div class="card-who">Owner: {esc(epic["owner"])}</div><div class="lanes">{lanes}</div></div>'
            f'<div class="progress"><span>{counts["done"]}/{total} done</span>'
            f'<div class="track"><div class="fill" style="width:{done_pct}%"></div></div></div></summary>'
            f'<div class="board">{"".join(columns)}</div></details></section>')


def pr_tables(prs):
    recent = [pr for pr in prs if days_since(pr["createdAt"]) <= URGENT_PR_DAYS]
    urgent = [pr for pr in prs if days_since(pr["createdAt"]) > URGENT_PR_DAYS]
    return ('<div class="pr-grid">'
            f'<div><h3>Up to {URGENT_PR_DAYS} days <span class="count">{len(recent)}</span></h3>{pr_table(recent)}</div>'
            f'<div class="urgent"><h3>Over {URGENT_PR_DAYS} days, urgent <span class="count">{len(urgent)}</span></h3>'
            f'{pr_table(urgent)}</div></div>')


def pr_table(prs):
    if not prs:
        return '<p class="empty">None.</p>'
    rows = []
    for pr in sorted(prs, key=lambda p: p["createdAt"]):
        state, label = review_state(pr)
        keys = sorted(title_keys_in(pr))
        rows.append(
            f'<tr><td>{pr_titled(pr)}</td><td>{" ".join(jira_link(k) for k in keys)}</td>'
            f'<td>{esc(pr["author"]["login"])}</td><td class="num">{days_since(pr["createdAt"])} d</td>'
            f'<td><span class="pill {state}">{label}</span></td><td>{ci_pills(pr)}</td></tr>')
    return ('<div class="table-wrap"><table><thead><tr><th>Title</th><th>Ticket</th><th>Author</th>'
            '<th class="num">Age</th><th>Review</th><th>CI</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def attention(items):
    if not items:
        return '<p class="empty">Nothing to flag.</p>'
    return '<div class="attention">' + "".join(
        f'<div class="attention-item"><div>{subject}</div><div class="attention-action">{action}</div></div>'
        for subject, action in items) + "</div>"


def mine(my_prs, review_prs, my_tickets):
    def pr_items(prs):
        if not prs:
            return '<p class="empty">None.</p>'
        return "<ul class='mine-list'>" + "".join(
            f'<li>{pr_titled(pr)}<div class="pills">'
            f'<span class="pill {review_state(pr)[0]}">{review_state(pr)[1]}</span> {ci_pills(pr)}'
            f'<span class="age">{days_since(pr["createdAt"])} d</span></div></li>'
            for pr in sorted(prs, key=lambda p: p["createdAt"])) + "</ul>"

    tickets = ("<ul class='mine-list'>" + "".join(
        f'<li>{jira_link(t["key"])} {esc(t["summary"])}<div class="pills"><span class="pill draft">{esc(t["status"])}</span>'
        f'<span class="age">{t["days_in_status"]} d in status</span></div></li>'
        for t in my_tickets) + "</ul>") if my_tickets else '<p class="empty">None.</p>'
    return ('<div class="mine">'
            f'<div class="mine-box"><h3>Review requested from me <span class="count">{len(review_prs)}</span></h3>{pr_items(review_prs)}</div>'
            f'<div class="mine-box"><h3>My open PRs <span class="count">{len(my_prs)}</span></h3>{pr_items(my_prs)}</div>'
            f'<div class="mine-box"><h3>My tickets in progress <span class="count">{len(my_tickets)}</span></h3>{tickets}</div>'
            '</div>')


def ci_pill(ci):
    return f'<span class="pill {ci[0]}">{esc(ci[1])}</span>' if ci else ""


def day_label(day):
    return "Today" if days_since(day.isoformat()) == 0 else "Yesterday"


def changes_section(changes, ci_by_url):
    if changes is None:
        return '<p class="empty">First run: changes show up from the next one.</p>'
    by_day = {}
    for c in changes:
        at = dt.datetime.fromisoformat(c["at"])
        by_day.setdefault(at.date(), []).append(
            f'<li><span class="time">{at.strftime("%H:%M")}</span>'
            f'<span class="pill {c["tone"]}">{esc(c["label"])}</span><div class="what">{c["text"]}</div>'
            f'<span class="ci">{ci_pill(ci_by_url.get(c["item"]))}</span></li>')
    if not by_day:
        return f'<p class="empty">Nothing in the last {CHANGES_HOURS} h.</p>'
    return '<div class="recent-changes">' + "".join(
        f'<h3>{day_label(day)}</h3><ul>{"".join(items)}</ul>' for day, items in by_day.items()) + "</div>"


TUI_GRIDS = {"attention": "2ch minmax(0,1fr)", "team prs": "22ch 18ch 6ch 11ch 4ch", "my desk": "22ch 18ch 6ch 11ch 4ch",
             "epics": "9ch 20ch 6ch minmax(0,1fr)", "changes": "12ch 18ch minmax(0,1fr)"}
TUI_TICKET_GRID = "22ch 18ch 6ch minmax(0,1fr)"


def tui_field(name, value):
    return f'<div><span class="dim k">{name:<9}</span>{value}</div>'


def tui_entry(row, detail, url, copy, search, grid=None, group=None):
    return {"row": row, "detail": detail, "url": url, "copy": copy, "search": search, "grid": grid, "group": group}


def tui_attention(subject, action):
    url = re.search(r'href="([^"]+)"', subject).group(1)
    return tui_entry(f'<span class="bad">▲</span><span class="ell">{esc(plain(subject))}</span>',
                     f'<div class="h">{esc(plain(subject))}</div><div class="warn">{esc(plain(action))}</div>'
                     f'<div class="sep">──</div><a href="{esc(url)}">{esc(url)}</a>',
                     url, url, f"{plain(subject)} {plain(action)}")


def tui_pr(pr, by_key, group=None):
    tone, label = review_state(pr)
    ci_tone, ci_label = TUI_CI[pr["ci"]]
    conflict = '<span class="bad">⚠ conflict</span>' if pr["mergeable"] == "CONFLICTING" else "<span></span>"
    row = (f'<span>{esc(tui_repo(pr))}#{pr["number"]}</span><span class="{TUI_REVIEW[tone]}">{label.lower()}</span>'
           f'<span class="{ci_tone}">{ci_label}</span>{conflict}<span class="dim r">{days_since(pr["createdAt"])}d</span>')
    events = [(c["committedDate"], '<span class="dim">commit</span>') for c in pr["commits"]] + [
        (r["submittedAt"], f'<span class="{TUI_REVIEW_EVENTS.get(r["state"], "blue")}">{r["state"].lower().replace("_", " ")}</span> '
                           f'{esc(r["author"]["login"])}') for r in pr["reviews"]]
    linked = [by_key[k] for k in sorted(ticket_keys_in(pr)) if k in by_key]
    detail = (f'<div class="h">{esc(pr["title"])}</div>'
              + tui_field("pr", f'<a href="{esc(pr["url"])}">{esc(tui_repo(pr))}#{pr["number"]}</a> <span class="dim">by</span> '
                                f'{esc(pr["author"]["login"])} <span class="dim">open</span> {days_since(pr["createdAt"])}d')
              + tui_field("review", label + (' <span class="warn">review requested</span>' if pr["reviewRequests"] else ""))
              + tui_field("ci", pr["ci"]) + tui_field("merge", "conflicts" if pr["mergeable"] == "CONFLICTING" else "clean")
              + ("".join(tui_field("ticket", f'{esc(t["key"])} <span class="dim">({esc(t["status"])})</span> {esc(t["summary"])}')
                         for t in linked) or tui_field("ticket", "—"))
              + '<div class="sep">── activity ──</div>'
              + "".join(f'<div><span class="dim">{local_time(at)}</span>  {what}</div>' for at, what in sorted(events, reverse=True)[:10]))
    return tui_entry(row, detail, pr["url"], pr["url"], f'{pr["repo"]} {pr["number"]} {pr["title"]} {pr["author"]["login"]}', group=group)


def tui_ticket(ticket, prs):
    linked = [pr for pr in prs if ticket["key"] in ticket_keys_in(pr)]
    row = (f'<span>{esc(ticket["key"])}</span><span class="warn">{esc(ticket["status"].lower())}</span>'
           f'<span class="dim r">{ticket["days_in_status"]}d</span><span class="dim ell">{esc(ticket["summary"])}</span>')
    detail = (f'<div class="h">{esc(ticket["summary"])}</div>'
              + tui_field("ticket", f'<a href="{esc(config.settings.jira_browse)}{esc(ticket["key"])}">{esc(ticket["key"])}</a>')
              + tui_field("status", f'{esc(ticket["status"])} <span class="dim">for</span> {ticket["days_in_status"]}d')
              + ("".join(tui_field("pr", f'<a href="{esc(pr["url"])}">{esc(tui_repo(pr))}#{pr["number"]}</a> {review_state(pr)[1]}')
                         for pr in linked) or tui_field("pr", "—")))
    return tui_entry(row, detail, config.settings.jira_browse + ticket["key"], ticket["key"], f'{ticket["key"]} {ticket["summary"]}',
                     TUI_TICKET_GRID, "my tickets")


def tui_epic(epic, tickets):
    done = sum(1 for t in tickets if t["column"] == "done")
    filled = round(20 * done / len(tickets)) if tickets else 0
    row = (f'<span>{esc(epic["key"])}</span><span class="ok">{"█" * filled}<span class="dim">{"░" * (20 - filled)}</span></span>'
           f'<span class="dim r">{done}/{len(tickets)}</span><span class="ell">{esc(epic["summary"])}</span>')
    groups = ""
    for key, label, _ in COLUMNS:
        column = [t for t in tickets if t["column"] == key]
        if column and key != "done":
            groups += f'<div class="sep">── {label.lower()} ({len(column)}) ──</div>' + "".join(
                f'<div><a href="{esc(config.settings.jira_browse)}{esc(t["key"])}">{esc(t["key"])}</a> {esc(t["summary"])} '
                f'<span class="dim">{esc(t["assignee"])}</span></div>' for t in column)
    detail = (f'<div class="h">{esc(epic["summary"])}</div>'
              + tui_field("epic", f'<a href="{esc(config.settings.jira_browse)}{esc(epic["key"])}">{esc(epic["key"])}</a> <span class="dim">({esc(epic["status"])})</span>')
              + tui_field("owner", esc(epic["owner"])) + tui_field("done", f"{done}/{len(tickets)}") + groups)
    return tui_entry(row, detail, config.settings.jira_browse + epic["key"], epic["key"], f'{epic["key"]} {epic["summary"]}')


def tui_change(change):
    url = re.search(r'href="([^"]+)"', change["text"])
    url = url.group(1) if url else ""
    row = (f'<span class="dim">{change["at"][5:10]} {change["at"][11:16]}</span>'
           f'<span class="{TUI_REVIEW.get(change["tone"], "dim")}">{esc(change["label"].lower())}</span>'
           f'<span class="ell">{esc(plain(change["text"]))}</span>')
    detail = f'<div class="h">{esc(change["label"])}</div><div>{change["text"]}</div>' + tui_field("at", change["at"].replace("T", " "))
    return tui_entry(row, detail, url, url, f'{plain(change["text"])} {change["label"]}')


def tui_pane(number, name, entries, empty):
    rows, details, group = "", "", None
    for i, e in enumerate(entries):
        if e["group"] and e["group"] != group:
            group = e["group"]
            rows += f'<li class="group">{group}</li>'
        rows += (f'<li class="tui-item" data-i="{i}" data-url="{esc(e["url"])}" data-copy="{esc(e["copy"])}" '
                 f'data-search="{esc(e["search"].lower())}" style="grid-template-columns:{e["grid"] or TUI_GRIDS[name]}">{e["row"]}</li>')
        details += f'<div class="tui-detail" data-i="{i}">{e["detail"]}</div>'
    listing = f"<ul>{rows}</ul>" if entries else f'<p class="dim">{empty}</p>'
    return (f'<div class="tui-pane" data-tab="{number}"><section class="tui-panel"><span class="title">{name}</span>'
            f'<label class="filter">/ <input placeholder="filter" aria-label="Filter {name}"></label>{listing}</section>'
            f'<section class="tui-panel"><span class="title">details</span>{details}</section></div>')


def tui(attention_found, prs, review_prs, my_prs, my_tickets, epics, tickets_by_epic, changes, by_key):
    desk = ([tui_pr(pr, by_key, "review requested") for pr in review_prs] + [tui_pr(pr, by_key, "my prs") for pr in my_prs]
            + [tui_ticket(t, prs) for t in my_tickets])
    tabs = [("attention", [tui_attention(*item) for item in attention_found], "nothing to flag"),
            ("team prs", [tui_pr(pr, by_key) for pr in sorted(prs, key=lambda p: p["createdAt"])], "no open prs"),
            ("my desk", desk, "desk is empty"),
            ("epics", [tui_epic(e, tickets_by_epic[e["key"]]) for e in epics], "no epics"),
            ("changes", [tui_change(c) for c in changes or []], f"no changes in the last {CHANGES_HOURS} h")]
    nav = "".join(f'<button type="button" class="tui-tab" data-tab="{n}">[{n}] {name} <span class="dim">{len(entries)}</span></button>'
                  for n, (name, entries, _) in enumerate(tabs, 1))
    return nav, "".join(tui_pane(n, *tab) for n, tab in enumerate(tabs, 1))


def render(epics, tickets_by_epic, prs, merged_by_ticket, review_prs, my_tickets, changes, now, template):
    all_tickets = [t for ts in tickets_by_epic.values() for t in ts]
    attention_found = attention_items(all_tickets, prs, merged_by_ticket)
    my_prs = [pr for pr in prs if pr["author"]["login"] == config.settings.github_user]
    tui_tabs, tui_panes = tui(attention_found, prs, review_prs, my_prs, my_tickets, epics, tickets_by_epic,
                              changes, {t["key"]: t for t in all_tickets})

    boards = "".join(board(e, tickets_by_epic[e["key"]]) for e in epics)
    return (template
            .replace("{{DATE}}", dt.datetime.now().strftime("%d/%m/%Y %H:%M"))
            .replace("{{MINE}}", mine(my_prs, review_prs, my_tickets))
            .replace("{{CHANGES}}", changes_section(changes, {url: pr["ci"] for url, pr in now["prs"].items()}))
            .replace("{{CHANGES_HOURS}}", str(CHANGES_HOURS))
            .replace("{{ATTENTION}}", attention(attention_found))
            .replace("{{TUI_TABS}}", tui_tabs)
            .replace("{{TUI_PANES}}", tui_panes)
            .replace("{{PRS}}", pr_tables(prs))
            .replace("{{TEAM}}", ", ".join(config.settings.team))
            .replace("{{ORG}}", esc(config.settings.github_org))
            .replace("{{LOGO}}", LOGO)
            .replace("{{BOARDS}}", boards))


OUT = STATE_DIR / "board.html"


def build():
    found = collect()
    template = (Path(__file__).with_name("tablero-template.html")).read_text()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(found["epics"], found["tickets_by_epic"], found["prs"], found["merged_by_ticket"], found["review_prs"],
                          found["my_tickets"], found["changes"], found["now"], template))
    return {**found, "out": OUT}


def main():
    found = config.load()
    if found is None:
        sys.exit("No config found. Run `python -m tarkon config` first.")
    config.use(found)
    print(build()["out"])
