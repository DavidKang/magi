import re
from bisect import bisect_left
from dataclasses import dataclass, replace
from pathlib import Path

from rich.console import Console
from rich.syntax import Syntax
from rich.text import Text
from textual.content import Content

from .. import rows
from ..domain import changes
from ..domain.ages import ago, days_since
from ..domain.labels import BLOCKED_LABEL, blocked
from ..domain.mine import my_changes, my_epics, my_prs
from ..domain.review import CI_LABELS, STALE_PR_DAYS, TURNS, review_state, turn
from ..domain.status import COLUMNS, STATUS_COLUMNS, kanban_order, status_label, ticket_order
from . import theme
from .theme import COLORS

# The keys a details text points at, each in a span of its own: the web page has no keys, so it drops these spans.
OPEN_HINT, MORE_HINT = " · c to open", " c to read it all"
KEY_HINTS = (OPEN_HINT, MORE_HINT)
DIFF_BACKGROUNDS = {"+": "#12261e", "-": "#2d1418"}
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
    ticket: str = None
    progress: tuple = None
    fold: int = 0


ZERO_WIDTH_SPACE = "\u200b"


def escape(value):
    text = str(value).replace("[", r"\[")
    return text + ZERO_WIDTH_SPACE if text.endswith("\\") else text


def link(url, label):
    # Markup ignores repr's backslash escapes, so a url with both quotes could close the action early: encoded, it opens the same page.
    url = url.replace("'", "%27").replace('"', "%22")
    return f"[{COLORS['accent']} underline @click=app.open_link({url!r})]{escape(label)}[/]"


def colored(tone, value):
    return f"[{COLORS[tone]}]{escape(value)}[/]"


def field(name, value):
    return f"{colored('blue', name.ljust(9))}{value}"


def heading(value):
    return f"[b]{escape(value)}[/b]"


def separator(label=""):
    return f'[b]{colored("accent", f"── {label} ──" if label else "──")}[/b]'


def pr_entry(pr, by_key, settings, asked=False):
    row = rows.pr_row(pr, by_key, settings)
    group, missing = row["turn"]
    missing, tone = ("your review", "warn") if yours(group, asked) else (missing, TURN_TONES[group])
    cells = [(Text(row["title"]), ""), (row["author"], "dim"), (missing, f"{tone}-pill"), (f'{row["age"]}d', "dim-right"),
             (rows.tui_repo(pr), "dim-right")]
    pushed = max((c["committedDate"] for c in pr.commits), default=None)
    lines = [heading(row["title"]), "",
             field("pr", f'{link(row["url"], row["ref"])} {colored("dim", "by")} {escape(row["author"])} '
                         f'{colored("dim", "open")} {row["age"]}d' + (f' {colored("dim", "· last push")} {days_since(pushed)}d ago' if pushed else "")),
             field("status", colored(tone, missing))]
    lines += [field("failing", " · ".join(link(c["url"], c["name"]) for c in pr.failed_checks))] if pr.failed_checks else []
    lines += [field("ticket", f'{link(t["url"], t["key"])} {colored("dim", f"({t["status"]})")} {escape(t["summary"])}')
              for t in row["tickets"]] or [field("ticket", "—")]
    items = review_items(pr)
    lines += comments_field(len(items)) if items else []
    lines += ["", separator("activity"), *activity(row["events"])]
    return Entry(cells, "\n".join(lines), pr.url, pr.url,
                 f'{pr.repo} {rows.tui_repo(pr)} {pr.number} {pr.title} {row["author"]}',
                 (f'{row["ref"]} · {pr.title}', items), ticket=next(iter(row["keys"]), None))


def activity(events, told=()):
    """Newest first, with the commits of a day in one line, naming its year when it is not the newest day's; told are the changes Magi saw on the board."""
    days = {}
    for event in events:
        if not event["state"]:
            days.setdefault(rows.local(event["at"]).date(), []).append(rows.local(event["at"]))
    newest = max(days, default=None)
    commits = [(max(ats), day.strftime("%b %d" if day.year == newest.year else "%b %d %Y").ljust(12),
                colored("dim", f"{len(ats)} commit" + "s" * (len(ats) > 1))) for day, ats in days.items()]
    reviews = [(rows.local(e["at"]), rows.local_time(e["at"]), f'{state_label(e)} {escape(e["author"])}') for e in events if e["state"]]
    seen = [(rows.local(c["at"]), rows.local_time(c["at"]), told_change(c)) for c in told]
    return [f'{colored("dim", when)}  {what}' for _, when, what in sorted(commits + reviews + seen, reverse=True)[:10]]


def told_change(change):
    """A change in its PR's timeline: a status move reads Draft → Awaiting review, and only a ticket names itself."""
    left = changes.moved_from(change)
    ref = change["subject"]["ref"] if change["subject"]["kind"] == "ticket" else None
    what = " ".join(part for part in (ref, change["note"], None if left else change["aside"]) if part)
    label = colored(rows.TUI_REVIEW.get(change["tone"], "dim"), change["label"])
    return " ".join(part for part in (f"{escape(left)} → {label}" if left else label, escape(what)) if part)


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
    style = f"{COLORS['accent']} underline @click=app.open_review(0)"
    return [field("comments", f"[{style}]{count}[/][{style}]{OPEN_HINT}[/]")]


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


def diff_text(hunk, path, width):
    lexer = Syntax.guess_lexer(path)
    lines = hunk.splitlines()
    starts = [int(number) for match in map(HUNK_HEADER.match, lines) if match for number in match.groups()]
    digits = len(str(max(starts, default=0) + len(lines)))
    columns = 1 if all(line[:1] in "+@\\" for line in lines) else 2
    gutter = columns * (digits + 1)
    # Long lines go on below their own code, so the diff fits its box instead of scrolling sideways.
    room = max(width - gutter - 1, 1)
    text = Text(no_wrap=True)
    old = new = 0
    for i, line in enumerate(lines):
        if i:
            text.append("\n")
        start = HUNK_HEADER.match(line)
        if start or line.startswith("\\"):
            old, new = (int(start[1]), int(start[2])) if start else (old, new)
            heading = Text(line, COLORS["blue" if start else "dim"], overflow="fold")
            for n, piece in enumerate(heading.wrap(Console(), max(width - gutter, 1))):
                text.append("\n" * bool(n) + " " * gutter)
                text.append_text(piece)
            continue
        sign = line[:1] if line[:1] in "+-" else " "
        background = DIFF_BACKGROUNDS.get(sign, COLORS["bg"])
        numbers = f'{"" if sign == "+" else old:>{digits}} ' * (columns == 2) + f'{"" if sign == "-" else new:>{digits}} '
        text.append(numbers, COLORS["accent" if i == len(lines) - 1 else "dim"])
        text.append(sign, f"{COLORS[DIFF_SIGNS[sign]]} on {background}")
        code = Syntax("", lexer, theme="github-dark", background_color=background).highlight(line[1:])
        code.right_crop(1)
        code.no_wrap, code.overflow = False, "fold"
        for n, piece in enumerate(code.wrap(Console(), room) if code else [code]):
            if n:
                text.append("\n" + " " * gutter)
                text.append(" ", f"on {background}")
            text.append_text(piece)
            text.append(" " * (room - piece.cell_len), f"on {background}")
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
    if theme.frame():
        segments = round(10 * done / len(tickets)) if tickets else 0
        bar.append("█ " * segments, COLORS["progress"])
        bar.append("█ " * (10 - segments), COLORS[EPIC_REST[theme.frame()]])
    else:
        bar.append("█" * filled, COLORS["progress"])
        bar.append("░" * (20 - filled), COLORS["dim"])
    return Entry([(epic.key, ""), (bar, ""), (f"{done}/{len(tickets)}", "dim-right"), (epic.summary, "")],
                 "\n".join(lines), settings.jira_browse + epic.key, epic.key, f'{epic.key} {epic.summary}', progress=(done, len(tickets)))


def change_entry(change, told, history, author):
    url = change["item"]
    text = changes.change_text(change)
    # A ticket's key leads its title already; a PR's ref goes beside its state.
    state = f'{change["label"]} - {change["subject"]["ref"]}' if change["subject"]["kind"] == "pr" else change["label"]
    lines = [heading(state), "", link(url, text) if url else escape(text), "", separator("timeline"), *activity(history, told)]
    return Entry([(f'{change["at"][5:10]} {change["at"][11:16]}', "dim"), (change["label"].lower(), rows.TUI_REVIEW.get(change["tone"], "dim")),
                  (author or "", "dim"), (text, "")],
                 "\n".join(lines), url, url, f'{text} {change["label"]}')


def ticket_entry(ticket, prs, settings):
    row = rows.ticket_row(ticket, prs, settings)
    url, status = row["url"], row["status"]
    detail = ticket.detail
    kind = " · ".join(escape(value) for value in ((detail.type, detail.priority) if detail else ()) if value)
    lines = [heading(ticket.summary), "", field("ticket", link(url, ticket.key) + (f" {colored('dim', '·')} {kind}" if kind else "")),
             field("status", colored(status_tone(ticket.status), status))]
    if detail:
        epic = detail.epic
        lines += [field("labels", f' {colored("dim", "·")} '.join(label_tag(label) for label in detail.labels) or "—"),
                  field("epic", f'{link(settings.jira_browse + epic["key"], epic["key"])} {escape(epic["summary"])}' if epic else "—"),
                  field("creator", f'{escape(detail.creator)} {colored("dim", "· updated")} {days_since(detail.updated)}d ago')]
    items = ticket_items(ticket, settings)
    lines += comments_field(len(detail.comments)) if detail and detail.comments else []
    lines += pr_list(row["prs"])
    if detail and detail.links:
        lines += ["", separator("links")]
        for other in detail.links:
            lines += [f'• {colored("dim", other["relation"])} {link(settings.jira_browse + other["key"], other["key"])} '
                      f'{colored("dim", f"({status_label(other["status"])})")}', f'  {escape(other["summary"])}']
    shown = detail.description.splitlines() if detail and detail.description else []
    lines += ["", separator("description"), *(escape(line) for line in shown)] if shown else []
    return Entry([(ticket.key, ""), (ticket.summary, "")], "\n".join(lines), url, ticket.key,
                 f'{ticket.key} {ticket.summary} {status}', (f'{ticket.key} · {ticket.summary}', items), group=status, fold=len(shown))


def folded(detail, fold, kept):
    """A detail keeping only the first lines of its last `fold` ones, the description's, and a hint to read them all when it cuts any."""
    if kept >= fold:
        return detail
    lines = detail.split("\n")
    return "\n".join(lines[:len(lines) - fold + kept] + [colored("accent", "…") + colored("accent", MORE_HINT)])


def fitted(detail, fold, width, height):
    """A detail folded to the most description lines that fit a box of this size, the whole of it when it all fits."""
    def overflows(kept):
        return len(Content.from_markup(folded(detail, fold, kept)).wrap(width)) > height
    # Keeping more lines never takes fewer rows, so the first count that overflows is found by halving.
    return folded(detail, fold, max(0, bisect_left(range(fold + 1), True, key=overflows) - 1))


def status_tone(status):
    """A status reads in its column's colour, as the changes feed tells a move to it; a status no column holds reads plain."""
    column = STATUS_COLUMNS.get(status)
    return rows.TUI_REVIEW[changes.STATUS_TONES[column]] if column else "fg"


def label_tag(label):
    return f"[b]{colored('bad', label)}[/b]" if label == BLOCKED_LABEL else colored("warn", label)


def pr_list(prs):
    """A ticket's PRs, one per line in aligned columns: each one's link, its review in its colour, who opened it and how long ago."""
    if not prs:
        return []
    refs, states = (max(len(pr[key]) for pr in prs) for key in ("ref", "review"))
    return ["", separator(f"prs ({len(prs)})")] + [
        f'• {link(pr["url"], pr["ref"])}{" " * (refs - len(pr["ref"]))}  {colored(pr["tone"], pr["review"])}{" " * (states - len(pr["review"]))}  '
        f'{escape(pr["author"])} {colored("dim", "·")} {pr["age"]}d' for pr in prs]


def kanban_entry(ticket, prs, settings, mine):
    """A ticket on the kanban board: whether it is blocked, who has it, mine in the accent colour,
    what its oldest PR misses and the days since it last changed."""
    pr = min(rows.prs_naming(ticket.key, prs, settings), key=lambda found: found.created_at, default=None)
    group, missing = turn(pr) if pr else (None, "")
    # My tickets off the board carry no assignee, and one cached before the detail fetch no detail.
    detail = ticket.detail
    cells = [(ticket.key, ""), ("blocked", "bad-pill") if detail and blocked(ticket) else ("", ""), (ticket.assignee or "", "accent" if mine else "dim"),
             (missing, f"{TURN_TONES[group]}-pill" if pr else ""), (f"{days_since(detail.updated)}d" if detail else "", "dim-right"), (ticket.summary, "")]
    return replace(ticket_entry(ticket, prs, settings), cells=cells)


# A factory ticket waiting for you raises a flag and a blocked review an alarm; a ready one reads calm, a building one neutral.
STAGE_TONES = {"waiting-you": "warn-pill", "review-blocked": "bad-alarm", "building": "dim-pill", "ready": "ok-pill"}


def factory_entry(ticket, now, settings, board):
    """A factory ticket as a row, from its stage file and herdr beside what the board knows of it; now dates how long ago its stage changed."""
    tone = STAGE_TONES[ticket.stage]
    age, session, url = ago(ticket.since, now) if ticket.since else "", ticket.agent or "absent", settings.jira_browse + ticket.key
    known = board_ticket(ticket.key, board)
    summary = known.summary if known else ""
    epic = known.detail.epic if known and known.detail else None
    lines = [heading(summary or ticket.key), "",
             field("ticket", link(url, ticket.key) + (f' {colored("dim", f"({status_label(known.status)})")}' if known else ""))]
    lines += [field("epic", f'{link(settings.jira_browse + epic["key"], epic["key"])} {escape(epic["summary"])}')] if epic else []
    lines += [field("stage", colored(tone.rpartition("-")[0], ticket.stage) + (colored("dim", f" · {age} ago") if age else "")),
              field("session", escape(session) + (colored("dim", " · g jumps to it") if ticket.pane else ""))]
    for pr in rows.prs_naming(ticket.key, board["prs"], settings) if board else []:
        ci_tone, ci = CI_LABELS[pr.ci]
        lines += [field("pr", f'{link(pr.url, f"{rows.tui_repo(pr)}#{pr.number}")} {escape(review_state(pr)[1])} '
                              f'{colored("dim", "·")} {colored(rows.TUI_REVIEW[ci_tone], ci)}')]
        lines += [field("failing", " · ".join(link(c["url"], c["name"]) for c in pr.failed_checks))] if pr.failed_checks else []
    lines += ["", escape(ticket.detail)] if ticket.detail else []
    lines += ["", separator("agent"), *(escape(line) for line in ticket.output)] if ticket.output else []
    return Entry([(ticket.key, ""), (ticket.stage, tone), (age, "dim-right"), (session, "dim"), (ticket.detail or summary, "")],
                 "\n".join([*lines, "", separator(), link(url, url)]), url, ticket.key,
                 f"{ticket.key} {ticket.stage} {session} {ticket.detail} {summary}")


def board_ticket(key, board):
    """The board's own ticket for key: one of mine, with its details, else one of the epics'; None when the board has none."""
    if not board:
        return None
    return next((t for t in board["my_tickets"] if t.key == key), None) or board["by_key"].get(key)


TURN_TONES = {"needs review": "blue", "on the author": "bad", "ready to merge": "ok", "drafts": "dim"}
PILL_CAPS = {"lcars": ("◖", "◗"), "nerv": ("▕", "▏"), "cyberpunk": ("◢", "◤")}
# Status cells: what a PR is missing as a pill and a critical age's alarm. LCARS draws both as pills.
STATUS_KINDS = ("pill", "alarm")
# A PR row's days cell, before the repo at the right edge.
DAYS_CELL = -2
# NERV leaves the undone segments dark, after nerv-ui's sync bars.
EPIC_REST = {"lcars": "line", "nerv": "raised", "cyberpunk": "raised"}

def yours(group, asked):
    """A PR that asks for my review and waits on reviewers is mine to review."""
    return asked and group == "needs review"


def team_pr_entries(prs, by_key, settings, asked):
    """Team PRs by whose turn it is, oldest first, with my review requests leading."""
    def order(pr):
        group = turn(pr)[0]
        return TURNS.index(group), not yours(group, pr.url in asked), pr.created_at
    return [turn_entry(pr_entry(pr, by_key, settings, pr.url in asked), turn(pr)[0], days_since(pr.created_at) > STALE_PR_DAYS)
            for pr in sorted(prs, key=order)]


def group_name(group):
    return group.upper() if theme.frame() else group


def turn_entry(entry, group, stale):
    """The days of a PR open over three days turn red: a frame draws them as an alarm."""
    entry = replace(entry, group=group_name(group))
    if not stale:
        return entry
    cells = list(entry.cells)
    cells[DAYS_CELL] = (cells[DAYS_CELL][0], "bad-alarm" if theme.frame() else "bad-right")
    return replace(entry, cells=cells)


def entries(board, settings):
    prs, by_key = board["prs"], board["by_key"]
    return {**board_entries(board, settings, board["kanban"], prs, board["changes"], board["epics"]),
            "mine_prs": [pr_entry(pr, by_key, settings) for pr in sorted(board["my_prs"], key=lambda p: p.created_at)],
            "mine_tickets": [ticket_entry(t, prs, settings) for t in sorted(board["my_tickets"], key=ticket_order)]}


def mine_entries(board, settings):
    """The boxes with only my work: my tickets not done, even off the board, my PRs and the ones asking for my review,
    the changes on them and on my tickets, and the epics holding my tickets."""
    keys = {t.key for t in board["my_tickets"]}
    on_board = {t.key for t in board["kanban"]}
    # Mine on the board first, in its Jira rank, then the ones off it.
    tickets = [t for t in board["kanban"] if t.key in keys] + [t for t in board["my_tickets"] if t.key not in on_board]
    prs = my_prs(board["my_prs"], board["review_prs"])
    return board_entries(board, settings, tickets, prs, my_changes(board["changes"], prs, keys, settings.jira_browse),
                         my_epics(board["epics"], board["tickets_by_epic"], keys))


def board_entries(board, settings, tickets, prs, found, epics):
    histories = board["histories"]
    mine = {t.key for t in board["my_tickets"]}
    return {"kanban": [kanban_entry(t, board["prs"], settings, t.key in mine) for t in sorted(tickets, key=kanban_order)],
            "prs": team_pr_entries(prs, board["by_key"], settings, {pr.url for pr in board["review_prs"]}),
            "changes": [change_entry(c, changes.group_changes(found, c["group"], histories), histories.get(c["group"], []),
                                     changes.group_author(found, c["group"]))
                        for c in changes.latest(found, "group")],
            "epics": [epic_entry(e, board["tickets_by_epic"][e.key], settings) for e in epics]}


def pill(value, width, tone):
    if not value:
        return Text(" " * width)
    body, label = width - 4, value.upper().lstrip("✓✗…–⚠ ")
    label = label if len(label) <= body else label[:body - 1] + "…"
    left, right = PILL_CAPS[theme.frame()]
    # NERV outlines its badges in their colour instead of filling them, after nerv-ui's.
    fill = f"bold {COLORS[tone]}" if theme.frame() == "nerv" else f"{COLORS['bg']} on {COLORS[tone]}"
    return Text.assemble((left, COLORS[tone]), (f" {label.ljust(body)} ", fill), (right, COLORS[tone]))


def status(value, width, tone, kind):
    if theme.frame() == "lcars" or kind == "pill":
        return pill(value, width, tone)
    return Text(f"▲ {value.upper()}".rjust(width), f"bold {COLORS[tone]}")


def cell_row(entry, widths):
    text = Text(no_wrap=True, overflow="ellipsis")
    for (value, tone), width in zip(entry.cells, widths):
        kind = tone.rpartition("-")[2]
        if kind in STATUS_KINDS:
            tone = tone.removesuffix(f"-{kind}")
            value = status(value, width, tone, kind) if theme.frame() else value
        if isinstance(value, Text):
            if width is not None:
                value = value.copy()
                value.truncate(width, overflow="ellipsis", pad=True)
            text.append_text(value)
            text.append(" ")
            continue
        if width is not None:
            value = value[:width].rjust(width) if tone.endswith("-right") else value[:width].ljust(width)
        text.append(value + " ", COLORS.get(tone.removesuffix("-right")) if tone else None)
    return text
