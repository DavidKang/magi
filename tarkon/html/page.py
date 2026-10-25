"""Render the board as an html page, the browser version of Tarkon."""

import base64
import datetime as dt
import html
import sys
from pathlib import Path

from .. import config, rows
from ..adapters.paths import STATE_DIR
from ..domain.ages import days_since
from ..domain.attention import attention_items
from ..domain.changes import CHANGES_HOURS, change_text, subject_text
from ..domain.keys import title_keys_in, title_parts
from ..domain.review import CI_LABELS, review_state
from ..domain.status import COLUMNS, UnmappedStatus, status_label
from ..rows import TUI_CI, TUI_REVIEW, TUI_REVIEW_EVENTS, local_time

URGENT_PR_DAYS = 3
LOGO = "data:image/png;base64," + base64.b64encode((Path(__file__).parent.parent / "logo.png").read_bytes()).decode()
LOGO_LCARS = "data:image/png;base64," + base64.b64encode((Path(__file__).parent.parent / "logo-black.png").read_bytes()).decode()


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


def jira_link(key, settings):
    return f'<a class="key" href="{esc(settings.jira_browse + key)}">{JIRA_ICON}{esc(key)}</a>'


def github_link(url, text, tooltip=""):
    title = f' title="{esc(tooltip)}"' if tooltip else ""
    linked, rest = title_parts(text)
    return f'<a href="{esc(url)}"{title}>{GITHUB_ICON}{esc(linked)}</a>' + (f" {esc(rest)}" if rest else "")


def pr_titled(pr):
    return github_link(pr.url, pr.title, f'{pr.repo}#{pr.number}')


def ticket_titled(ticket, settings):
    return f'{jira_link(ticket.key, settings)} {esc(ticket.summary)}'


def subject_html(subject, settings):
    if subject["kind"] == "pr":
        return github_link(subject["url"], subject["title"], subject["ref"])
    return jira_link(subject["ref"], settings) + (f' {esc(subject["title"])}' if subject["title"] else "")


def change_html(change, settings):
    return (subject_html(change["subject"], settings) + (f' {esc(change["note"])}' if change["note"] else "")
            + (f' <span class="age">{esc(change["aside"])}</span>' if change["aside"] else ""))


def ci_pills(pr):
    tone, label = CI_LABELS[pr.ci]
    conflict = ' <span class="pill changes">Conflicts</span>' if pr.mergeable == "CONFLICTING" else ""
    return f'<span class="pill {tone}">{label}</span>{conflict}'


def pr_chip(pr):
    state, label = review_state(pr)
    return (f'<a class="pr {state}" href="{esc(pr.url)}" title="{esc(pr.title)}">'
            f'{esc(pr.repo)}#{pr.number} · {label}</a>')


def card(ticket, settings):
    age = f'updated {days_since(ticket.updated)} d ago' if ticket.updated else ""
    prs = "".join(pr_chip(pr) for pr in ticket.prs)
    return (f'<li class="card"><div class="card-top">{jira_link(ticket.key, settings)}'
            f'<span class="age">{age}</span></div>'
            f'<div class="card-title">{esc(ticket.summary)}</div>'
            f'<div class="card-who">{esc(ticket.assignee)}</div>'
            f'{f"<div class=prs>{prs}</div>" if prs else ""}</li>')


def board(epic, tickets, settings):
    counts = {key: sum(1 for t in tickets if t.column == key) for key, _, _ in COLUMNS}
    total = len(tickets)
    done_pct = round(100 * counts["done"] / total) if total else 0
    columns = []
    for key, label, _ in COLUMNS:
        cards = [t for t in tickets if t.column == key]
        body = "".join(card(t, settings) for t in cards)
        if key == "done" and cards:
            body = f'<details><summary>Show {len(cards)}</summary><ul class="cards">{body}</ul></details>'
        elif cards:
            body = f'<ul class="cards">{body}</ul>'
        else:
            body = '<p class="empty">—</p>'
        columns.append(f'<div class="col col-{key}"><h4>{label} <span class="count">{counts[key]}</span></h4>{body}</div>')
    lanes = "".join(f'<span>{label} <span class="count">{counts[key]}</span></span>' for key, label, _ in COLUMNS)
    return (f'<section class="epic" id="{epic.key}"><details class="epic-toggle"><summary class="epic-head">'
            f'<div>{jira_link(epic.key, settings)}<h3>{esc(epic.summary)}</h3>'
            f'<div class="card-who">Owner: {esc(epic.owner)}</div><div class="lanes">{lanes}</div></div>'
            f'<div class="progress"><span>{counts["done"]}/{total} done</span>'
            f'<div class="track"><div class="fill" style="width:{done_pct}%"></div></div></div></summary>'
            f'<div class="board">{"".join(columns)}</div></details></section>')


def pr_tables(prs, settings):
    recent = [pr for pr in prs if days_since(pr.created_at) <= URGENT_PR_DAYS]
    urgent = [pr for pr in prs if days_since(pr.created_at) > URGENT_PR_DAYS]
    return ('<div class="pr-grid">'
            f'<div><h3>Up to {URGENT_PR_DAYS} days <span class="count">{len(recent)}</span></h3>{pr_table(recent, settings)}</div>'
            f'<div class="urgent"><h3>Over {URGENT_PR_DAYS} days, urgent <span class="count">{len(urgent)}</span></h3>'
            f'{pr_table(urgent, settings)}</div></div>')


def pr_table(prs, settings):
    if not prs:
        return '<p class="empty">None.</p>'
    body = []
    for pr in sorted(prs, key=lambda p: p.created_at):
        state, label = review_state(pr)
        keys = sorted(title_keys_in(pr, settings.jira_project))
        body.append(
            f'<tr><td>{pr_titled(pr)}</td><td>{" ".join(jira_link(k, settings) for k in keys)}</td>'
            f'<td>{esc(pr.author["login"])}</td><td class="num">{days_since(pr.created_at)} d</td>'
            f'<td><span class="pill {state}">{label}</span></td><td>{ci_pills(pr)}</td></tr>')
    return ('<div class="table-wrap"><table><thead><tr><th>Title</th><th>Ticket</th><th>Author</th>'
            '<th class="num">Age</th><th>Review</th><th>CI</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def attention(items, settings):
    if not items:
        return '<p class="empty">Nothing to flag.</p>'
    return '<div class="attention">' + "".join(
        f'<div class="attention-item"><div>{subject_html(item["subject"], settings)}</div><div class="attention-action">{esc(item["reason"])}</div></div>'
        for item in items) + "</div>"


def mine(my_prs, review_prs, my_tickets, settings):
    def pr_items(prs):
        if not prs:
            return '<p class="empty">None.</p>'
        return "<ul class='mine-list'>" + "".join(
            f'<li>{pr_titled(pr)}<div class="pills">'
            f'<span class="pill {review_state(pr)[0]}">{review_state(pr)[1]}</span> {ci_pills(pr)}'
            f'<span class="age">{days_since(pr.created_at)} d</span></div></li>'
            for pr in sorted(prs, key=lambda p: p.created_at)) + "</ul>"

    tickets = ("<ul class='mine-list'>" + "".join(
        f'<li>{jira_link(t.key, settings)} {esc(t.summary)}<div class="pills"><span class="pill draft">{esc(status_label(t.status))}</span></div></li>'
        for t in my_tickets) + "</ul>") if my_tickets else '<p class="empty">None.</p>'
    return ('<div class="mine">'
            f'<div class="mine-box"><h3>Review requested from me <span class="count">{len(review_prs)}</span></h3>{pr_items(review_prs)}</div>'
            f'<div class="mine-box"><h3>My open PRs <span class="count">{len(my_prs)}</span></h3>{pr_items(my_prs)}</div>'
            f'<div class="mine-box"><h3>My open tickets <span class="count">{len(my_tickets)}</span></h3>{tickets}</div>'
            '</div>')


def ci_pill(ci):
    return f'<span class="pill {ci[0]}">{esc(ci[1])}</span>' if ci else ""


def day_label(day):
    return "Today" if days_since(day.isoformat()) == 0 else "Yesterday"


def changes_section(changes, ci_by_url, settings):
    if changes is None:
        return '<p class="empty">First run: changes show up from the next one.</p>'
    by_day = {}
    for c in changes:
        at = dt.datetime.fromisoformat(c["at"])
        by_day.setdefault(at.date(), []).append(
            f'<li><span class="time">{at.strftime("%H:%M")}</span>'
            f'<span class="pill {c["tone"]}">{esc(c["label"])}</span><div class="what">{change_html(c, settings)}</div>'
            f'<span class="ci">{ci_pill(ci_by_url.get(c["item"]))}</span></li>')
    if not by_day:
        return f'<p class="empty">Nothing in the last {CHANGES_HOURS} h.</p>'
    return '<div class="recent-changes">' + "".join(
        f'<h3>{day_label(day)}</h3><ul>{"".join(items)}</ul>' for day, items in by_day.items()) + "</div>"


TUI_GRIDS = {"attention": "2ch minmax(0,1fr)", "team prs": "22ch 18ch 6ch 11ch 4ch", "my desk": "22ch 18ch 6ch 11ch 4ch",
             "epics": "9ch 20ch 6ch minmax(0,1fr)", "changes": "12ch 18ch minmax(0,1fr)"}
TUI_TICKET_GRID = "22ch 18ch minmax(0,1fr)"


def tui_field(name, value):
    return f'<div><span class="dim k">{name:<9}</span>{value}</div>'


def tui_entry(row, detail, url, copy, search, grid=None, group=None):
    return {"row": row, "detail": detail, "url": url, "copy": copy, "search": search, "grid": grid, "group": group}


def tui_attention(item):
    url, title, reason = item["subject"]["url"], subject_text(item["subject"]), item["reason"]
    return tui_entry(f'<span class="bad">▲</span><span class="ell">{esc(title)}</span>',
                     f'<div class="h">{esc(title)}</div><div class="warn">{esc(reason)}</div>'
                     f'<div class="sep">──</div><a href="{esc(url)}">{esc(url)}</a>',
                     url, url, f"{title} {reason}")


def tui_pr(pr, by_key, settings, group=None):
    data = rows.pr_row(pr, by_key, settings)
    tone, label = data["review"]
    ci_tone, ci_label = TUI_CI[data["ci"]]
    conflict = '<span class="bad">⚠ conflict</span>' if data["conflict"] else "<span></span>"
    row = (f'<span>{esc(data["ref"])}</span><span class="{TUI_REVIEW[tone]}">{label.lower()}</span>'
           f'<span class="{ci_tone}">{ci_label}</span>{conflict}<span class="dim r">{data["age"]}d</span>')
    events = [(e["at"], f'<span class="{TUI_REVIEW_EVENTS.get(e["state"], "blue")}">{e["state"].lower().replace("_", " ")}</span> '
                        f'{esc(e["author"])}' if e["state"] else '<span class="dim">commit</span>') for e in data["events"]]
    detail = (f'<div class="h">{esc(data["title"])}</div>'
              + tui_field("pr", f'<a href="{esc(data["url"])}">{esc(data["ref"])}</a> <span class="dim">by</span> '
                                f'{esc(data["author"])} <span class="dim">open</span> {data["age"]}d')
              + tui_field("review", label + (' <span class="warn">review requested</span>' if data["review_requested"] else ""))
              + tui_field("ci", data["ci"]) + tui_field("merge", "conflicts" if data["conflict"] else "clean")
              + ("".join(tui_field("ticket", f'{esc(t["key"])} <span class="dim">({esc(t["status"])})</span> {esc(t["summary"])}')
                         for t in data["tickets"]) or tui_field("ticket", "—"))
              + '<div class="sep">── activity ──</div>'
              + "".join(f'<div><span class="dim">{local_time(at)}</span>  {what}</div>' for at, what in sorted(events, reverse=True)[:10]))
    return tui_entry(row, detail, pr.url, pr.url, f'{pr.repo} {pr.number} {pr.title} {data["author"]}', group=group)


def tui_ticket(ticket, prs, settings):
    data = rows.ticket_row(ticket, prs, settings)
    row = (f'<span>{esc(data["key"])}</span><span class="warn">{esc(data["status"])}</span>'
           f'<span class="dim ell">{esc(data["summary"])}</span>')
    detail = (f'<div class="h">{esc(data["summary"])}</div>'
              + tui_field("ticket", f'<a href="{esc(data["url"])}">{esc(data["key"])}</a>')
              + tui_field("status", esc(data["status"]))
              + ("".join(tui_field("pr", f'<a href="{esc(pr["url"])}">{esc(pr["ref"])}</a> {pr["review"]}')
                         for pr in data["prs"] if pr["project_key"]) or tui_field("pr", "—")))
    return tui_entry(row, detail, data["url"], data["key"], f'{data["key"]} {data["summary"]}', TUI_TICKET_GRID, "my tickets")


def tui_epic(epic, tickets, settings):
    done = sum(1 for t in tickets if t.column == "done")
    filled = round(20 * done / len(tickets)) if tickets else 0
    row = (f'<span>{esc(epic.key)}</span><span class="ok">{"█" * filled}<span class="dim">{"░" * (20 - filled)}</span></span>'
           f'<span class="dim r">{done}/{len(tickets)}</span><span class="ell">{esc(epic.summary)}</span>')
    groups = ""
    for key, label, _ in COLUMNS:
        column = [t for t in tickets if t.column == key]
        if column and key != "done":
            groups += f'<div class="sep">── {label.lower()} ({len(column)}) ──</div>' + "".join(
                f'<div><a href="{esc(settings.jira_browse)}{esc(t.key)}">{esc(t.key)}</a> {esc(t.summary)} '
                f'<span class="dim">{esc(t.assignee)}</span></div>' for t in column)
    detail = (f'<div class="h">{esc(epic.summary)}</div>'
              + tui_field("epic", f'<a href="{esc(settings.jira_browse)}{esc(epic.key)}">{esc(epic.key)}</a> <span class="dim">({esc(epic.status)})</span>')
              + tui_field("owner", esc(epic.owner)) + tui_field("done", f"{done}/{len(tickets)}") + groups)
    return tui_entry(row, detail, settings.jira_browse + epic.key, epic.key, f'{epic.key} {epic.summary}')


def tui_change(change, settings):
    url = change["item"]
    row = (f'<span class="dim">{change["at"][5:10]} {change["at"][11:16]}</span>'
           f'<span class="{TUI_REVIEW.get(change["tone"], "dim")}">{esc(change["label"].lower())}</span>'
           f'<span class="ell">{esc(change_text(change))}</span>')
    detail = f'<div class="h">{esc(change["label"])}</div><div>{change_html(change, settings)}</div>' + tui_field("at", change["at"].replace("T", " "))
    return tui_entry(row, detail, url, url, f'{change_text(change)} {change["label"]}')


def tui_pane(number, name, entries, empty):
    items, details, group = "", "", None
    for i, e in enumerate(entries):
        if e["group"] and e["group"] != group:
            group = e["group"]
            items += f'<li class="group">{group}</li>'
        items += (f'<li class="tui-item" data-i="{i}" data-url="{esc(e["url"])}" data-copy="{esc(e["copy"])}" '
                 f'data-search="{esc(e["search"].lower())}" style="grid-template-columns:{e["grid"] or TUI_GRIDS[name]}">{e["row"]}</li>')
        details += f'<div class="tui-detail" data-i="{i}">{e["detail"]}</div>'
    listing = f"<ul>{items}</ul>" if entries else f'<p class="dim">{empty}</p>'
    return (f'<div class="tui-pane" data-tab="{number}"><section class="tui-panel"><span class="title">{name}</span>'
            f'<label class="filter">/ <input placeholder="filter" aria-label="Filter {name}"></label>{listing}</section>'
            f'<section class="tui-panel"><span class="title">details</span>{details}</section></div>')


def tui(attention_found, prs, review_prs, my_prs, my_tickets, epics, tickets_by_epic, changes, by_key, settings):
    desk = ([tui_pr(pr, by_key, settings, "review requested") for pr in review_prs] + [tui_pr(pr, by_key, settings, "my prs") for pr in my_prs]
            + [tui_ticket(t, prs, settings) for t in my_tickets])
    tabs = [("attention", [tui_attention(item) for item in attention_found], "nothing to flag"),
            ("team prs", [tui_pr(pr, by_key, settings) for pr in sorted(prs, key=lambda p: p.created_at)], "no open prs"),
            ("my desk", desk, "desk is empty"),
            ("epics", [tui_epic(e, tickets_by_epic[e.key], settings) for e in epics], "no epics"),
            ("changes", [tui_change(c, settings) for c in changes or []], f"no changes in the last {CHANGES_HOURS} h")]
    nav = "".join(f'<button type="button" class="tui-tab" data-tab="{n}">[{n}] {name} <span class="dim">{len(entries)}</span></button>'
                  for n, (name, entries, _) in enumerate(tabs, 1))
    return nav, "".join(tui_pane(n, *tab) for n, tab in enumerate(tabs, 1))


def render(epics, tickets_by_epic, prs, merged_by_ticket, review_prs, my_tickets, changes, now, template, settings):
    all_tickets = [t for ts in tickets_by_epic.values() for t in ts]
    attention_found = attention_items(all_tickets, prs, merged_by_ticket, settings)
    my_prs = [pr for pr in prs if pr.author["login"] == settings.github_user]
    tui_tabs, tui_panes = tui(attention_found, prs, review_prs, my_prs, my_tickets, epics, tickets_by_epic,
                              changes, {t.key: t for t in all_tickets}, settings)

    boards = "".join(board(e, tickets_by_epic[e.key], settings) for e in epics)
    return (template
            .replace("{{DATE}}", dt.datetime.now().strftime("%d/%m/%Y %H:%M"))
            .replace("{{MINE}}", mine(my_prs, review_prs, my_tickets, settings))
            .replace("{{CHANGES}}", changes_section(changes, {url: pr["ci"] for url, pr in now["prs"].items()}, settings))
            .replace("{{CHANGES_HOURS}}", str(CHANGES_HOURS))
            .replace("{{ATTENTION}}", attention(attention_found, settings))
            .replace("{{TUI_TABS}}", tui_tabs)
            .replace("{{TUI_PANES}}", tui_panes)
            .replace("{{PRS}}", pr_tables(prs, settings))
            .replace("{{TEAM}}", ", ".join(settings.team))
            .replace("{{ORG}}", esc(settings.github_org))
            .replace("{{LOGO}}", LOGO)
            .replace("{{LOGO_LCARS}}", LOGO_LCARS)
            .replace("{{BOARDS}}", boards))


OUT = STATE_DIR / "board.html"


def build(collect, settings):
    found = collect(settings)
    template = (Path(__file__).with_name("template.html")).read_text()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(found["epics"], found["tickets_by_epic"], found["prs"], found["merged_by_ticket"], found["review_prs"],
                          found["my_tickets"], found["changes"], found["now"], template, settings))
    return {**found, "out": OUT}


def main(collect):
    found = config.load()
    if found is None:
        sys.exit("No config found. Run `python -m tarkon config` first.")
    try:
        print(build(collect, found)["out"])
    except UnmappedStatus as error:
        sys.exit(str(error))
