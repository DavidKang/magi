import asyncio
import datetime as dt
import math
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image as PILImage
from rich.syntax import Syntax
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, ContentSwitcher, Footer, Input, OptionList, Static, Tab, Tabs
from textual.widgets.option_list import Option
from textual_image.widget import Image, get_cell_size

from .. import board as g
from .. import config, fetch, jira, rows, storage

THEMES = {"default": {"ok": "#56d364", "bad": "#ff7b72", "warn": "#e3b341", "blue": "#79c0ff", "dim": "#6e7a87", "accent": "#21cfac",
                       "bg": "#0d1117", "fg": "#d1d9e0", "line": "#30363d", "raised": "#161b22", "title": "#21cfac",
                       "pick": "#1f6feb40", "pick-focus": "#1f6feb66", "veil": "#01040980"},
          "lcars": {"ok": "#99cc66", "bad": "#ff6666", "warn": "#ffcc66", "blue": "#99ccff", "dim": "#9999cc", "accent": "#ff9900",
                    "bg": "#000000", "fg": "#ffcc99", "line": "#cc99cc", "raised": "#1a1426", "title": "#000000",
                    "pick": "#ff990033", "pick-focus": "#ff990059", "veil": "#000000c0"}}
COLORS = dict(THEMES["default"])
theme = "default"
# A refresh costs about 5 s and at most 9 of GitHub's 5000 GraphQL points an hour.
REFRESH_SECONDS = 5 * 60
REFRESH_COOLDOWN = 30
CACHE = Path.home() / ".cache" / "tarkon" / "cache.json"
LOGO = Path(__file__).parent.parent / "logo.png"
LOGO_ROWS = 1
DESCRIPTION_LINES = 12
PR_WIDTHS = [15, 9, 10, 17, 4, 10, 4]
DIFF_BACKGROUNDS = {"+": "#12261e", "-": "#2d1418", " ": "#0d1117"}
DIFF_SIGNS = {"+": "ok", "-": "bad", " ": "dim"}
HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
CHANGE_WIDTHS = [12, 18, None]
NO_CHANGES = f"no changes in the last {g.CHANGES_HOURS} h"
SECTIONS = {"attention": ("attention", "nothing to flag", [2, None]),
            "prs": ("team prs", "no open prs", PR_WIDTHS),
            "changes": ("changes", NO_CHANGES, CHANGE_WIDTHS),
            "epics": ("epics", "no epics", [9, 20, 6, None]),
            "mine_prs": ("my prs", "no open prs", PR_WIDTHS),
            "mine_tickets": ("my tickets", "no open tickets", [10, None])}
TABS = {"overview": ["attention", "prs", "changes", "epics"], "mine": ["mine_prs", "mine_tickets"]}
NUMBERS = {key: n for n, key in enumerate(SECTIONS, len(TABS) + 1)}
TAB_OF = {key: tab for tab, keys in TABS.items() for key in keys}


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


def use_theme(name):
    global theme
    theme = name
    COLORS.update(THEMES[name])


def stardate(when):
    return f"{when:%y%j}.{when.hour * 10 // 24}"


def panel_title(key, count):
    number, name = NUMBERS[key], SECTIONS[key][0]
    title = f"{number:02d}-{name.upper()}" if theme == "lcars" else f"[{number}] {name}"
    return title if count is None else f"{title} {count}"


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
    url, title, reason = item["subject"]["url"], g.subject_text(item["subject"]), item["reason"]
    return Entry([("▲", "bad"), (title, "")],
                 "\n".join([heading(title), "", colored("warn", reason), "", separator(), link(url, url)]),
                 url, url, f"{title} {reason}")


def pr_entry(pr, by_key, settings):
    row = rows.pr_row(pr, by_key, settings)
    tone, label = row["review"]
    ci_tone, ci_label = g.TUI_CI[row["ci"]]
    conflict = ("⚠ conflict" if row["conflict"] else "", "bad-pill")
    cells = [(row["ref"], ""), (row["code"], "blue"), (row["author"], "dim"),
             (label.lower(), f"{g.TUI_REVIEW[tone]}-pill"), (ci_label, f"{ci_tone}-pill"), conflict, (f'{row["age"]}d', "dim-right")]
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
    lines += ["", separator("activity")] + [f'{colored("dim", g.local_time(at))}  {what}' for at, what in sorted(events, reverse=True)[:10]]
    return Entry(cells, "\n".join(lines), pr.url, pr.url,
                 f'{pr.repo} {g.tui_repo(pr)} {pr.number} {pr.title} {row["author"]}',
                 (f'{row["ref"]} · {pr.title}', items))


def state_label(review):
    return colored(g.TUI_REVIEW_EVENTS.get(review["state"], "blue"), review["state"].lower().replace("_", " "))


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
    row = Text(review["state"].lower().replace("_", " "), COLORS[g.TUI_REVIEW_EVENTS.get(review["state"], "blue")])
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
                               "comments": [colored("dim", g.local_time(c["createdAt"])), *indented(c["body"])]})
             for c in pr.conversation]
    items = [item for _, item in sorted(reviews + notes, key=lambda pair: pair[0])]
    for thread in pr.threads:
        comments = []
        for comment in thread["comments"]:
            comments += ["" if comments else None,
                         f'[b]{escape(comment["author"]["login"])}[/b] {colored("dim", g.local_time(comment["createdAt"]))}',
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
                           "comments": [colored("dim", g.local_time(c["created"])), *indented(c["body"])]}
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
    for key, label, _ in jira.COLUMNS:
        column = [t for t in tickets if t.column == key]
        if column and key != "done":
            lines += ["", separator(f"{label.lower()} ({len(column)})")]
            lines += [f'{link(settings.jira_browse + t.key, t.key)} {escape(t.summary)} {colored("dim", t.assignee)}' for t in column]
    bar = Text()
    bar.append("█" * filled, COLORS["ok"])
    bar.append("░" * (20 - filled), COLORS["dim"])
    return Entry([(epic.key, ""), (bar, ""), (f"{done}/{len(tickets)}", "dim-right"), (epic.summary, "")],
                 "\n".join(lines), settings.jira_browse + epic.key, epic.key, f'{epic.key} {epic.summary}')


def change_entry(change):
    url = change["item"]
    text = g.change_text(change)
    lines = [heading(change["label"]), "", link(url, text) if url else escape(text), "", field("at", change["at"].replace("T", " "))]
    return Entry([(f'{change["at"][5:10]} {change["at"][11:16]}', "dim"), (change["label"].lower(), g.TUI_REVIEW.get(change["tone"], "dim")),
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
                  field("created", f'{g.local_time(detail.created)} {colored("dim", "updated")} {fetch.days_since(detail.updated)}d ago'),
                  field("labels", escape(", ".join(detail.labels)) or "—")]
    lines += [field("pr", f'{link(pr["url"], pr["ref"])} {escape(pr["review"])}') for pr in row["prs"]] or [field("pr", "—")]
    items = ticket_items(ticket, settings)
    lines += comments_field(len(detail.comments)) if detail and detail.comments else []
    if detail and detail.links:
        lines += ["", separator("links")]
        for other in detail.links:
            lines += [f'• {colored("dim", other["relation"])} {link(settings.jira_browse + other["key"], other["key"])} '
                      f'{colored("dim", f"({jira.status_label(other["status"])})")}', f'  {escape(other["summary"])}']
    if detail and detail.description:
        shown = detail.description.splitlines()
        lines += ["", separator("description"), *(escape(line) for line in shown[:DESCRIPTION_LINES])]
        lines += [colored("dim", "… c to read it all")] if len(shown) > DESCRIPTION_LINES else []
    return Entry([(ticket.key, ""), (ticket.summary, "")], "\n".join(lines), url, ticket.key,
                 f'{ticket.key} {ticket.summary} {status}', (f'{ticket.key} · {ticket.summary}', items), group=status)


def entries(board, settings):
    prs, by_key = board["prs"], board["by_key"]
    return {"attention": [attention_entry(item) for item in board["attention"]],
            "prs": [pr_entry(pr, by_key, settings) for pr in sorted(prs, key=lambda p: p.created_at)],
            "changes": [change_entry(c) for c in board["changes"]],
            "epics": [epic_entry(e, board["tickets_by_epic"][e.key], settings) for e in board["epics"]],
            "mine_prs": [pr_entry(pr, by_key, settings) for pr in sorted(board["my_prs"], key=lambda p: p.created_at)],
            "mine_tickets": [ticket_entry(t, prs, settings) for t in sorted(board["my_tickets"], key=jira.ticket_order)]}


def pill(value, width, tone):
    if not value:
        return Text(" " * width)
    body, label = width - 2, value.upper().lstrip("✓✗…–⚠ ")
    label = label if len(label) <= body else label[:body - 1] + "…"
    return Text.assemble(("◖", COLORS[tone]), (label.ljust(body), f"{COLORS['bg']} on {COLORS[tone]}"), ("◗", COLORS[tone]))


def cell_row(entry, widths):
    text = Text(no_wrap=True, overflow="ellipsis")
    for (value, tone), width in zip(entry.cells, widths):
        if tone.endswith("-pill"):
            tone = tone.removesuffix("-pill")
            value = pill(value, width, tone) if theme == "lcars" else value
        if isinstance(value, Text):
            text.append_text(value)
            text.append(" ")
            continue
        if width is not None:
            value = value[:width].rjust(width) if tone.endswith("-right") else value[:width].ljust(width)
        text.append(value + " ", COLORS.get(tone.removesuffix("-right")) if tone else None)
    return text


def open_in_browser(url):
    subprocess.Popen(["open", url])


def pbcopy(text):
    subprocess.run(["pbcopy"], input=text, text=True, check=True)


class SideButton(Static):
    def __init__(self, key):
        super().__init__(f"{NUMBERS[key]:02d}\n{SECTIONS[key][0].upper()}", id=f"side-{key}", classes="side")
        self.key = key

    def on_click(self):
        self.app.action_focus_box(NUMBERS[self.key])


class Board(OptionList):
    BINDINGS = [Binding("j", "cursor_down", show=False), Binding("k", "cursor_up", show=False),
                Binding("enter", "app.open_current", "open")]

    def __init__(self, section, **kwargs):
        super().__init__(**kwargs)
        self.section = section

    def on_focus(self):
        self.app.board_focused(self)


def logo_image(rows, cell):
    source = PILImage.open(LOGO)
    columns = math.ceil(rows * cell.height * source.width / source.height / cell.width)
    image = PILImage.new("RGBA", (round(source.height * columns * cell.width / (rows * cell.height)), source.height))
    image.paste(source, ((image.width - source.width) // 2, 0))
    return image, columns


def logo():
    image, columns = logo_image(LOGO_ROWS, get_cell_size())
    widget = Image(image, id="logo")
    widget.styles.width = columns
    return widget


class ThreadList(OptionList):
    BINDINGS = [Binding("j", "cursor_down", "thread", key_display="j/k"), Binding("k", "cursor_up", show=False),
                Binding("enter", "screen.open", "open")]


class ReviewScreen(ModalScreen):
    BINDINGS = [Binding("y", "copy", "copy link"), Binding("escape", "close", "close"), Binding("q", "close", show=False)]

    def __init__(self, heading, items, start):
        super().__init__()
        self.heading, self.items, self.start = heading, items, start

    def compose(self) -> ComposeResult:
        with Vertical(id="review"):
            with Horizontal():
                options = [option for i, item in enumerate(self.items) for option in (None, Option(item["row"], id=str(i)))][1:]
                yield ThreadList(*options, id="review-list")
                with Vertical(id="review-thread"):
                    yield Static(id="review-place")
                    with VerticalScroll(id="review-diff-box"):
                        yield Static(id="review-diff")
                    with VerticalScroll(id="review-comments-box"):
                        yield Static(id="review-comments")
        yield Footer()

    def on_mount(self):
        self.query_one("#review").border_title = escape(self.heading)
        listing = self.query_one(ThreadList)
        listing.highlighted = self.start
        listing.focus()

    def current(self):
        return self.items[self.query_one(ThreadList).highlighted]

    def on_option_list_option_highlighted(self, event):
        event.stop()
        item = self.items[int(event.option.id)]
        self.query_one("#review-place", Static).update(item["place"])
        box = self.query_one("#review-diff-box")
        box.display = item["hunk"] is not None
        if item["hunk"]:
            self.query_one("#review-diff", Static).update(diff_text(item["hunk"], item["path"]))
            self.call_after_refresh(box.scroll_end, animate=False)
        self.query_one("#review-comments", Static).update("\n".join(item["comments"]))
        self.query_one("#review-comments-box").scroll_home(animate=False)

    def action_open(self):
        self.app.opener(self.current()["url"])

    def action_copy(self):
        self.app.action_copy_text(self.current()["url"])

    def action_close(self):
        self.dismiss()


CONFIG_FIELDS = {"team": ("GitHub users of your team", "alice, bob, carol"),
                 "jira_project": ("Jira project", "ACME"),
                 "github_user": ("Your GitHub user", "your-github-user"),
                 "github_org": ("GitHub organization", "acme"),
                 "jira_url": ("Jira site", "https://acme.atlassian.net")}

BOARD_ACTIONS = {"focus_tab", "focus_box", "focus_filter", "clear_filter", "copy_current", "refresh", "open_review", "toggle_theme"}


class ConfigScreen(Screen):
    AUTO_FOCUS = "Input"
    BINDINGS = [Binding("ctrl+s", "save", "save"), Binding("escape", "cancel", "cancel")]

    def __init__(self, current):
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="config"):
            with Horizontal(classes="masthead"):
                yield logo()
                yield Static("Tarkon config", classes="brand")
            for name, (label, placeholder) in CONFIG_FIELDS.items():
                yield Static(label, classes="label")
                yield Input(value=self.shown(name), placeholder=placeholder, id=f"config-{name}")
            with Horizontal(id="config-buttons"):
                yield Button("save", id="config-save")
                yield Button("cancel", id="config-cancel")
        yield Footer()

    def shown(self, name):
        if self.current is None:
            return ""
        value = getattr(self.current, name)
        return ", ".join(value) if isinstance(value, list) else value

    def on_button_pressed(self, event):
        if event.button.id == "config-save":
            self.action_save()
        else:
            self.action_cancel()

    def action_save(self):
        values = {name: self.query_one(f"#config-{name}", Input).value.strip() for name in CONFIG_FIELDS}
        missing = [CONFIG_FIELDS[name][0] for name, value in values.items() if not value]
        if missing:
            self.notify(f"Fill in every field: {', '.join(missing)}", severity="error", timeout=5)
            return
        values["team"] = values["team"].replace(",", " ").split()
        self.dismiss(config.Settings(**values, theme=self.current.theme if self.current else "default"))

    def action_cancel(self):
        if self.current is None:
            self.app.exit()
        else:
            self.dismiss(self.current)


class TarkonApp(App):
    TITLE = "Tarkon"
    AUTO_FOCUS = "Board"
    CSS_PATH = "app.tcss"
    BINDINGS = [*(Binding(str(n), f"focus_tab({n})", "tabs", key_display="1-2", show=n == 1) for n in range(1, len(TABS) + 1)),
                *(Binding(str(n), f"focus_box({n})", "boxes", key_display="3-8", show=n == 3) for n in NUMBERS.values()),
                Binding("slash", "focus_filter", "filter", key_display="/"),
                Binding("escape", "clear_filter", "clear", show=False),
                Binding("c", "open_review", "comments"),
                Binding("y", "copy_current", "copy"),
                Binding("r", "refresh", "refresh"),
                Binding("t", "toggle_theme", "theme"),
                Binding("q", "quit", "quit")]

    def __init__(self, load=None, opener=open_in_browser, copier=pbcopy, clock=time.time, cache=CACHE,
                 config_path=config.PATH, edit_config=False):
        super().__init__()
        self.config_path, self.edit_config = config_path, edit_config
        self.load = load or (lambda: g.collect(self.settings))
        self.opener, self.copier, self.clock, self.cache = opener, copier, clock, cache
        self.stamp = cache.with_name("last-refresh")
        self.refreshing = False
        self.last_refresh = None
        self.sections = {key: [] for key in SECTIONS}
        self.board = None
        self.settings = None
        self.updated_at = None
        self.refresh_failed = False
        self.current_section = "attention"

    def get_css_variables(self):
        return {**super().get_css_variables(), **{f"mc-{name}": value for name, value in COLORS.items()}}

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Static("TARKON", id="elbow")
            with Vertical(id="header-main"):
                yield Static(id="bar")
                with Horizontal(id="top", classes="masthead"):
                    yield logo()
                    yield Static("Tarkon", classes="brand")
                    yield Static("loading…", id="status")
        yield Tabs(*(Tab(f"[{n}] {tab.capitalize()}", id=f"tab-{tab}") for n, tab in enumerate(TABS, 1)))
        with Horizontal(classes="pane"):
            with Vertical(id="sidebar"):
                for key in SECTIONS:
                    yield SideButton(key)
                yield Static(id="side-fill")
            with ContentSwitcher(initial=f"pane-{next(iter(TABS))}", id="panes"):
                for tab, keys in TABS.items():
                    with Vertical(id=f"pane-{tab}"):
                        for key in keys:
                            with Vertical(id=f"panel-{key}", classes="panel") as panel:
                                panel.border_title = panel_title(key, None)
                                yield Input(placeholder="/ filter", id=f"filter-{key}", classes="filter")
                                yield Board(key, id=f"list-{key}")
            with VerticalScroll(classes="panel") as panel:
                panel.border_title = "details"
                yield Static(id="detail")
        yield Footer()

    def check_action(self, action, parameters):
        return not isinstance(self.screen, (ConfigScreen, ReviewScreen)) or action not in BOARD_ACTIONS

    def on_mount(self):
        self.saved = config.load(self.config_path)
        if self.saved is None or self.edit_config:
            self.push_screen(ConfigScreen(self.saved), self.configured)
        else:
            self.start(self.saved)

    def configured(self, found):
        config.save(found, self.config_path)
        self.start(found, force=found != self.saved)

    def start(self, found, force=False):
        config.use(found)
        self.settings = found
        self.apply_theme(found.theme)
        saved = storage.read(self.cache)
        if saved:
            self.show_board(g.saved_board(saved["board"]), saved["at"])
        attempts = [saved["at"]] if saved else []
        if self.stamp.exists():
            attempts.append(float(self.stamp.read_text()))
        self.last_refresh = max(attempts, default=None)
        wait = 0 if self.last_refresh is None else self.last_refresh + REFRESH_COOLDOWN - self.clock()
        if force or wait <= 0:
            self.start_refresh()
        elif not saved:
            self.query_one("#status", Static).update(f"next refresh in {math.ceil(wait)}s")
            self.set_timer(wait, self.start_refresh)
        self.set_interval(REFRESH_SECONDS, self.start_refresh)

    def action_refresh(self):
        if self.refreshing:
            self.notify("refresh already running", timeout=3)
            return
        wait = self.last_refresh + REFRESH_COOLDOWN - self.clock()
        if wait > 0:
            self.notify(f"next refresh in {math.ceil(wait)}s", timeout=3)
            return
        self.start_refresh()

    def start_refresh(self):
        if self.refreshing:
            return
        self.refreshing = True
        self.last_refresh = self.clock()
        self.stamp.parent.mkdir(parents=True, exist_ok=True)
        self.stamp.write_text(str(self.last_refresh))
        self.query_one("#status", Static).update("refreshing…")
        self.fetch(self.last_refresh)

    @work(exclusive=True, exit_on_error=False)
    async def fetch(self, started):
        loop = asyncio.get_running_loop()
        outcome = loop.create_future()

        def load():
            try:
                found = (self.load(), None)
            except Exception as error:
                found = (None, error)
            try:
                loop.call_soon_threadsafe(lambda: outcome.done() or outcome.set_result(found))
            except RuntimeError:  # the app quit and closed its loop while the refresh ran
                pass

        # A daemon thread, not the loop's executor: quitting must not wait for acli and gh to finish.
        threading.Thread(target=load, daemon=True).start()
        board, error = await outcome
        if error:
            self.failed(error)
            return
        storage.write(self.cache, {"at": started, "board": board})
        self.show_board(board, started)

    def failed(self, error):
        self.refreshing = False
        self.refresh_failed = True
        self.query_one("#status", Static).update(f"[{COLORS['bad']}]refresh failed[/]")
        message = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error)
        self.notify(message, title="Refresh failed", severity="error", timeout=10, markup=False)

    def show_board(self, board, at):
        self.refreshing = False
        self.fill_sections(board)
        self.updated_at = at
        self.refresh_failed = False
        self.show_updated()
        self.current_board().focus()

    def show_updated(self):
        when = dt.datetime.fromtimestamp(self.updated_at)
        self.query_one("#status", Static).update(f"STARDATE {stardate(when)} · {when:%H:%M}" if theme == "lcars" else f"updated {when:%H:%M}")

    def title_panels(self):
        for key in SECTIONS:
            self.query_one(f"#panel-{key}").border_title = panel_title(key, len(self.sections[key]) if self.board else None)
        self.query_one("#detail").parent.border_title = "DETAILS" if theme == "lcars" else "details"

    def fill_sections(self, board):
        self.board = board
        self.sections = entries(board, self.settings)
        self.title_panels()
        for key in SECTIONS:
            self.fill(key)

    def apply_theme(self, name):
        use_theme(name)
        self.set_class(name == "lcars", "lcars")
        self.refresh_css()
        self.query_one("#bar", Static).update(Text("◗", f"{COLORS['accent']} on {COLORS['bg']}"))
        self.query_one("#top .brand", Static).update("TARKON" if name == "lcars" else "Tarkon")
        self.title_panels()
        if self.updated_at and not self.refreshing and not self.refresh_failed:
            self.show_updated()

    def action_toggle_theme(self):
        found = replace(self.settings, theme="default" if self.settings.theme == "lcars" else "lcars")
        config.save(found, self.config_path)
        config.use(found)
        self.settings = found
        self.apply_theme(found.theme)
        if self.board:
            self.fill_sections(self.board)

    def current_board(self):
        return self.query_one(f"#list-{self.current_section}", Board)

    def board_focused(self, board):
        self.current_section = board.section
        for button in self.query(SideButton):
            button.set_class(button.key == board.section, "-on")
        self.show_detail(board)

    def fill(self, key):
        board = self.query_one(f"#list-{key}", Board)
        query = self.query_one(f"#filter-{key}", Input).value.lower()
        _, empty, widths = SECTIONS[key]
        board.clear_options()
        shown = [(i, entry) for i, entry in enumerate(self.sections[key]) if query in entry.search.lower()]
        group = None
        for i, entry in shown:
            if entry.group and entry.group != group:
                group = entry.group
                size = sum(1 for _, other in shown if other.group == group)
                board.add_option(Option(Text(f"── {group} ({size}) ──", COLORS["dim"]), disabled=True))
            board.add_option(Option(cell_row(entry, widths), id=str(i)))
        if not self.sections[key]:
            board.add_option(Option(Text(empty, COLORS["dim"]), disabled=True))
        first = next((i for i in range(board.option_count) if not board.get_option_at_index(i).disabled), None)
        board.highlighted = first
        self.show_detail(board)

    def entry(self, board):
        option = board.highlighted_option
        return self.sections[board.section][int(option.id)] if option and option.id else None

    def current(self):
        return self.entry(self.current_board())

    def show_detail(self, board):
        if self.current_section != board.section:
            return
        entry = self.entry(board)
        self.query_one("#detail", Static).update(entry.detail if entry else "")

    def on_option_list_option_highlighted(self, event):
        self.show_detail(event.option_list)

    @on(Input.Changed, ".filter")
    def filter_changed(self, event):
        self.fill(event.input.id.removeprefix("filter-"))

    @on(Input.Submitted, ".filter")
    def filter_submitted(self, event):
        self.query_one(f"#list-{event.input.id.removeprefix('filter-')}", Board).focus()

    def action_focus_tab(self, number):
        tab = list(TABS)[number - 1]
        if TAB_OF[self.current_section] != tab:
            self.action_focus_box(NUMBERS[TABS[tab][0]])

    def action_focus_box(self, number):
        key = list(SECTIONS)[number - NUMBERS["attention"]]
        self.show_tab(TAB_OF[key])
        self.query_one(f"#list-{key}", Board).focus()

    def show_tab(self, tab):
        self.query_one(Tabs).active = f"tab-{tab}"
        self.query_one(ContentSwitcher).current = f"pane-{tab}"

    @on(Tabs.TabActivated)
    def tab_activated(self, event):
        tab = event.tab.id.removeprefix("tab-")
        self.query_one(ContentSwitcher).current = f"pane-{tab}"
        if TAB_OF[self.current_section] != tab:
            self.query_one(f"#list-{TABS[tab][0]}", Board).focus()

    def action_focus_filter(self):
        self.query_one(f"#filter-{self.current_section}", Input).focus()

    def action_clear_filter(self):
        key = self.current_section
        self.query_one(f"#filter-{key}", Input).value = ""
        self.fill(key)
        self.current_board().focus()

    def action_open_current(self):
        entry = self.current()
        if entry and entry.url:
            self.opener(entry.url)

    def action_open_review(self, index=0):
        entry = self.current()
        heading, items = entry.popup if entry and entry.popup else (None, [])
        if not items:
            self.notify("no review comments", timeout=2)
            return
        self.push_screen(ReviewScreen(heading, items, index))

    def action_open_link(self, url):
        self.opener(url)

    def action_copy_current(self):
        entry = self.current()
        if entry:
            self.action_copy_text(entry.copy)

    def action_copy_text(self, text):
        self.copier(text)
        self.notify(f"copied {text}", timeout=2)


def main(edit_config=False):
    app = TarkonApp(edit_config=edit_config)
    app.run()
    leave(app)


def leave(app):
    # Skip the interpreter's shutdown: it joins the pool workers of a running or failed refresh, after every queued acli and gh call.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(app.return_code or 0)
