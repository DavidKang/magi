import re
from dataclasses import dataclass, replace
from pathlib import Path

from rich.syntax import Syntax
from rich.text import Text

from .. import rows
from ..domain import changes
from ..domain.attention import STALE_PR_DAYS
from ..domain.ages import days_since
from ..domain.status import COLUMNS, status_label, ticket_order
from . import theme
from .theme import COLORS, THEMES

DESCRIPTION_LINES = 12
DIFF_BACKGROUNDS = {"+": "#12261e", "-": "#2d1418", " ": THEMES["default"]["bg"]}
DIFF_SIGNS = {"+": "ok", "-": "bad", " ": "dim"}
HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass
class Entry:
    cells: list
    detail: str
    url: str
    copy: str
    search: str
    popup: tuple = None
    group: str = None


ZERO_WIDTH_SPACE = "\u200b"


def escape(value):
    text = str(value).replace("[", r"\[")
    return text + ZERO_WIDTH_SPACE if text.endswith("\\") else text


def link(url, label):
    return f"[{COLORS['accent']} underline @click=app.open_link({url!r})]{escape(label)}[/]"


def colored(tone, value):
    return f"[{COLORS[tone]}]{escape(value)}[/]"


def field(name, value):
    return f"{colored('dim', name.ljust(9))}{value}"


def heading(value):
    return f"[b]{escape(value)}[/b]"


def separator(label=""):
    return colored("dim", f"── {label} ──" if label else "──")


def attention_entry(item):
    url, title, reason = item["subject"]["url"], changes.subject_text(item["subject"]), item["reason"]
    return Entry([("▲", "bad"), (title, "")],
                 "\n".join([heading(title), "", colored("warn", reason), "", separator(), link(url, url)]),
                 url, url, f"{title} {reason}")


def pr_entry(pr, by_key, settings):
    row = rows.pr_row(pr, by_key, settings)
    tone, label = row["review"]
    ci_tone, ci_label = rows.TUI_CI[row["ci"]]
    conflict = ("⚠ conflict" if row["conflict"] else "", "bad-pill")
    cells = [(row["ref"], ""), (row["code"], "blue"), (row["author"], "dim"),
             (label.lower(), f"{rows.TUI_REVIEW[tone]}-pill"), (ci_label, f"{ci_tone}-pill"), conflict, (f'{row["age"]}d', "dim-right")]
    events = [(e["at"], f'{state_label(e)} {escape(e["author"])}' if e["state"] else colored("dim", "commit")) for e in row["events"]]
    lines = [heading(row["title"]), "",
             field("pr", f'{link(row["url"], row["ref"])} {colored("dim", "by")} {escape(row["author"])} '
                         f'{colored("dim", "open")} {row["age"]}d'),
             field("review", escape(label) + (f' {colored("warn", "review requested")}' if row["review_requested"] else "")),
             field("ci", row["ci"]),
             field("merge", "conflicts" if row["conflict"] else "clean")]
    lines += [field("ticket", f'{link(t["url"], t["key"])} {colored("dim", f"({t["status"]})")} {escape(t["summary"])}')
              for t in row["tickets"]] or [field("ticket", "—")]
    items = review_items(pr)
    lines += comments_field(len(items)) if items else []
    lines += ["", separator("activity")] + [f'{colored("dim", rows.local_time(at))}  {what}' for at, what in sorted(events, reverse=True)[:10]]
    return Entry(cells, "\n".join(lines), pr.url, pr.url,
                 f'{pr.repo} {rows.tui_repo(pr)} {pr.number} {pr.title} {row["author"]}',
                 (f'{row["ref"]} · {pr.title}', items))


def state_label(review):
    return colored(rows.TUI_REVIEW_EVENTS.get(review["state"], "blue"), review["state"].lower().replace("_", " "))


def indented(body):
    return [f"  {escape(line)}" for line in body.strip().splitlines()]


def thread_place(thread):
    place = f'{thread["path"]}:{thread["line"]}' if thread["line"] else thread["path"]
    return colored("blue", place) + (f' {colored("warn", "outdated")}' if thread["isOutdated"] else "")


def thread_row(thread):
    first, count = thread["comments"][0], len(thread["comments"])
    name = Path(thread["path"]).name + (f':{thread["line"]}' if thread["line"] else "")
    row = Text(name, COLORS["blue"])
    row.append(" · outdated" if thread["isOutdated"] else "", COLORS["warn"])
    row.append("\n" + first["author"]["login"])
    row.append(f" · {count} comments" if count > 1 else "", COLORS["dim"])
    return preview(row, first["body"])


def review_row(review):
    row = Text(review["state"].lower().replace("_", " "), COLORS[rows.TUI_REVIEW_EVENTS.get(review["state"], "blue")])
    row.append("\n" + review["author"]["login"])
    return preview(row, review["body"])


def preview(row, body):
    row.append("\n" + " ".join(body.split()), COLORS["dim"])
    row.no_wrap, row.overflow = True, "ellipsis"
    return row


def note_row(kind, author, body):
    row = Text(kind, COLORS["blue"])
    row.append("\n" + author)
    return preview(row, body)


def review_items(pr):
    reviews = [(r["submittedAt"], {"row": review_row(r), "place": f'{escape(r["author"]["login"])} {state_label(r)}', "hunk": None,
                                   "path": None, "comments": indented(r["body"]), "url": pr.url})
               for r in pr.reviews if r["body"].strip()]
    notes = [(c["createdAt"], {"row": note_row("comment", c["author"]["login"], c["body"]), "place": f'{escape(c["author"]["login"])} {colored("blue", "commented")}',
                               "hunk": None, "path": None, "url": c["url"],
                               "comments": [colored("dim", rows.local_time(c["createdAt"])), *indented(c["body"])]})
             for c in pr.conversation]
    items = [item for _, item in sorted(reviews + notes, key=lambda pair: pair[0])]
    for thread in pr.threads:
        comments = []
        for comment in thread["comments"]:
            comments += ["" if comments else None,
                         f'[b]{escape(comment["author"]["login"])}[/b] {colored("dim", rows.local_time(comment["createdAt"]))}',
                         *indented(comment["body"])]
        items.append({"row": thread_row(thread), "place": thread_place(thread), "hunk": thread["comments"][0]["diffHunk"],
                      "path": thread["path"], "comments": [line for line in comments if line is not None],
                      "url": thread["comments"][0].get("url", pr.url)})
    return items


def comments_field(count):
    return [field("comments", f"[{COLORS['accent']} underline @click=app.open_review(0)]{count} · c to open[/]")]


def ticket_items(ticket, settings):
    url = settings.jira_browse + ticket.key
    detail = ticket.detail
    if not detail:
        return []
    description = [{"row": note_row("description", detail.creator, detail.description), "hunk": None, "path": None, "url": url,
                    "place": f'{escape(detail.creator)} {colored("blue", "description")}', "comments": indented(detail.description)}
                   ] if detail.description else []
    return description + [{"row": note_row("comment", c["author"], c["body"]), "hunk": None, "path": None,
                           "place": f'{escape(c["author"])} {colored("blue", "commented")}', "url": f'{url}?focusedCommentId={c["id"]}',
                           "comments": [colored("dim", rows.local_time(c["created"])), *indented(c["body"])]}
                          for c in detail.comments]


def diff_text(hunk, path):
    lexer = Syntax.guess_lexer(path)
    lines = hunk.splitlines()
    width = max(len(line) for line in lines) + 1
    starts = [int(number) for match in map(HUNK_HEADER.match, lines) if match for number in match.groups()]
    digits = len(str(max(starts, default=0) + len(lines)))
    columns = 1 if all(line[:1] in "+@\\" for line in lines) else 2
    text = Text(no_wrap=True)
    old = new = 0
    for i, line in enumerate(lines):
        if i:
            text.append("\n")
        start = HUNK_HEADER.match(line)
        if start or line.startswith("\\"):
            old, new = (int(start[1]), int(start[2])) if start else (old, new)
            text.append(" " * (columns * (digits + 1)) + line, COLORS["blue" if start else "dim"])
            continue
        sign = line[:1] if line[:1] in "+-" else " "
        background = DIFF_BACKGROUNDS[sign]
        numbers = f'{"" if sign == "+" else old:>{digits}} ' * (columns == 2) + f'{"" if sign == "-" else new:>{digits}} '
        text.append(numbers, COLORS["accent" if i == len(lines) - 1 else "dim"])
        text.append(sign, f"{COLORS[DIFF_SIGNS[sign]]} on {background}")
        code = Syntax("", lexer, theme="github-dark", background_color=background).highlight(line[1:])
        code.right_crop(1)
        text.append_text(code)
        text.append(" " * (width - len(line)), f"on {background}")
        old, new = old + (sign != "+"), new + (sign != "-")
    return text


def epic_entry(epic, tickets, settings):
    done = sum(1 for t in tickets if t.column == "done")
    filled = round(20 * done / len(tickets)) if tickets else 0
    lines = [heading(epic.summary), "",
             field("epic", f'{link(settings.jira_browse + epic.key, epic.key)} {colored("dim", f"({epic.status})")}'),
             field("owner", escape(epic.owner)), field("done", f"{done}/{len(tickets)}")]
    for key, label, _ in COLUMNS:
        column = [t for t in tickets if t.column == key]
        if column and key != "done":
            lines += ["", separator(f"{label.lower()} ({len(column)})")]
            lines += [f'{link(settings.jira_browse + t.key, t.key)} {escape(t.summary)} {colored("dim", t.assignee)}' for t in column]
    bar = Text()
    if theme.lcars():
        segments = round(10 * done / len(tickets)) if tickets else 0
        bar.append("█ " * segments, COLORS["ok"])
        bar.append("█ " * (10 - segments), COLORS["line"])
    else:
        bar.append("█" * filled, COLORS["ok"])
        bar.append("░" * (20 - filled), COLORS["dim"])
    return Entry([(epic.key, ""), (bar, ""), (f"{done}/{len(tickets)}", "dim-right"), (epic.summary, "")],
                 "\n".join(lines), settings.jira_browse + epic.key, epic.key, f'{epic.key} {epic.summary}')


def change_entry(change):
    url = change["item"]
    text = changes.change_text(change)
    lines = [heading(change["label"]), "", link(url, text) if url else escape(text), "", field("at", change["at"].replace("T", " "))]
    return Entry([(f'{change["at"][5:10]} {change["at"][11:16]}', "dim"), (change["label"].lower(), rows.TUI_REVIEW.get(change["tone"], "dim")),
                  (text, "")],
                 "\n".join(lines), url, url, f'{text} {change["label"]}')


def ticket_entry(ticket, prs, settings):
    row = rows.ticket_row(ticket, prs, settings)
    url, status = row["url"], row["status"]
    detail = ticket.detail
    kind = " · ".join(escape(value) for value in ((detail.type, detail.priority) if detail else ()) if value)
    lines = [heading(ticket.summary), "", field("ticket", link(url, ticket.key) + (f" {colored('dim', '·')} {kind}" if kind else "")),
             field("status", escape(status))]
    if detail:
        epic = detail.epic
        lines += [field("epic", f'{link(settings.jira_browse + epic["key"], epic["key"])} {escape(epic["summary"])}' if epic else "—"),
                  field("creator", escape(detail.creator)),
                  field("created", f'{rows.local_time(detail.created)} {colored("dim", "updated")} {days_since(detail.updated)}d ago'),
                  field("labels", escape(", ".join(detail.labels)) or "—")]
    lines += [field("pr", f'{link(pr["url"], pr["ref"])} {escape(pr["review"])}') for pr in row["prs"]] or [field("pr", "—")]
    items = ticket_items(ticket, settings)
    lines += comments_field(len(detail.comments)) if detail and detail.comments else []
    if detail and detail.links:
        lines += ["", separator("links")]
        for other in detail.links:
            lines += [f'• {colored("dim", other["relation"])} {link(settings.jira_browse + other["key"], other["key"])} '
                      f'{colored("dim", f"({status_label(other["status"])})")}', f'  {escape(other["summary"])}']
    if detail and detail.description:
        shown = detail.description.splitlines()
        lines += ["", separator("description"), *(escape(line) for line in shown[:DESCRIPTION_LINES])]
        lines += [colored("dim", "… c to read it all")] if len(shown) > DESCRIPTION_LINES else []
    return Entry([(ticket.key, ""), (ticket.summary, "")], "\n".join(lines), url, ticket.key,
                 f'{ticket.key} {ticket.summary} {status}', (f'{ticket.key} · {ticket.summary}', items), group=status)


def team_pr_entries(prs, by_key, settings):
    by_age = sorted(prs, key=lambda p: p.created_at)
    if not theme.lcars():
        return [pr_entry(pr, by_key, settings) for pr in by_age]
    return [priority_entry(pr_entry(pr, by_key, settings)) if days_since(pr.created_at) > STALE_PR_DAYS
            else replace(pr_entry(pr, by_key, settings), group="ROUTINE") for pr in by_age]


def priority_entry(entry):
    days, _ = entry.cells[-1]
    return replace(entry, cells=[*entry.cells[:-1], (days, "bad-pill")], group="PRIORITY ONE")


def entries(board, settings):
    prs, by_key = board["prs"], board["by_key"]
    return {"attention": [attention_entry(item) for item in board["attention"]],
            "prs": team_pr_entries(prs, by_key, settings),
            "changes": [change_entry(c) for c in board["changes"]],
            "epics": [epic_entry(e, board["tickets_by_epic"][e.key], settings) for e in board["epics"]],
            "mine_prs": [pr_entry(pr, by_key, settings) for pr in sorted(board["my_prs"], key=lambda p: p.created_at)],
            "mine_tickets": [ticket_entry(t, prs, settings) for t in sorted(board["my_tickets"], key=ticket_order)]}


def pill(value, width, tone):
    if not value:
        return Text(" " * width)
    body, label = width - 4, value.upper().lstrip("✓✗…–⚠ ")
    label = label if len(label) <= body else label[:body - 1] + "…"
    return Text.assemble(("◖", COLORS[tone]), (f" {label.ljust(body)} ", f"{COLORS['bg']} on {COLORS[tone]}"), ("◗", COLORS[tone]))


def cell_row(entry, widths):
    text = Text(no_wrap=True, overflow="ellipsis")
    for (value, tone), width in zip(entry.cells, widths):
        if tone.endswith("-pill"):
            tone = tone.removesuffix("-pill")
            value = pill(value, width, tone) if theme.lcars() else value
        if isinstance(value, Text):
            text.append_text(value)
            text.append(" ")
            continue
        if width is not None:
            value = value[:width].rjust(width) if tone.endswith("-right") else value[:width].ljust(width)
        text.append(value + " ", COLORS.get(tone.removesuffix("-right")) if tone else None)
    return text
