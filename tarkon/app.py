import datetime as dt
import json
import math
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image as PILImage
from rich.syntax import Syntax
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Input, OptionList, Static
from textual.widgets.option_list import Option
from textual_image.widget import Image, get_cell_size

from . import board as g
from . import config, fetch, web

COLORS = {"ok": "#56d364", "bad": "#ff7b72", "warn": "#e3b341", "blue": "#79c0ff", "dim": "#6e7a87"}
ACCENT = "#21cfac"
REFRESH_SECONDS = 20 * 60
REFRESH_COOLDOWN = 60
CACHE = Path.home() / ".cache" / "tarkon" / "cache.json"
LOGO = Path(__file__).with_name("logo.png")
LOGO_ROWS = 1
PR_WIDTHS = [15, 9, 10, 17, 4, 10, 4]
DIFF_BACKGROUNDS = {"+": "#12261e", "-": "#2d1418", " ": "#0d1117"}
DIFF_SIGNS = {"+": COLORS["ok"], "-": COLORS["bad"], " ": COLORS["dim"]}
HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
CHANGE_WIDTHS = [12, 18, None]
NO_CHANGES = f"no changes in the last {g.CHANGES_HOURS} h"
SECTIONS = {"attention": ("attention", "nothing to flag", [2, None]),
            "prs": ("team prs", "no open prs", PR_WIDTHS),
            "changes": ("changes", NO_CHANGES, CHANGE_WIDTHS),
            "epics": ("epics", "no epics", [9, 20, 6, None])}
NUMBERS = {key: n for n, key in enumerate(SECTIONS, 1)}


@dataclass
class Entry:
    cells: list
    detail: str
    url: str
    copy: str
    search: str
    pr: dict = None


ZERO_WIDTH_SPACE = "\u200b"


def escape(value):
    text = str(value).replace("[", r"\[")
    return text + ZERO_WIDTH_SPACE if text.endswith("\\") else text


def link(url, label):
    return f"[{ACCENT} underline @click=app.open_link({url!r})]{escape(label)}[/]"


def colored(tone, value):
    return f"[{COLORS[tone]}]{escape(value)}[/]"


def field(name, value):
    return f"{colored('dim', name.ljust(9))}{value}"


def heading(value):
    return f"[b]{escape(value)}[/b]"


def separator(label=""):
    return colored("dim", f"── {label} ──" if label else "──")


def attention_entry(subject, action):
    url = re.search(r'href="([^"]+)"', subject).group(1)
    title = g.plain(subject)
    return Entry([("▲", "bad"), (title, "")],
                 "\n".join([heading(title), "", colored("warn", g.plain(action)), "", separator(), link(url, url)]),
                 url, url, f"{title} {g.plain(action)}")


def pr_entry(pr, by_key):
    tone, label = g.review_state(pr)
    ci_tone, ci_label = g.TUI_CI[pr["ci"]]
    conflict = ("⚠ conflict", "bad") if pr["mergeable"] == "CONFLICTING" else ("", "")
    code = re.search(r"\[[A-Z][A-Z0-9]+-\d+\]", pr["title"])
    cells = [(f'{g.tui_repo(pr)}#{pr["number"]}', ""), (code.group() if code else "", "blue"), (pr["author"]["login"], "dim"),
             (label.lower(), g.TUI_REVIEW[tone]), (ci_label, ci_tone), conflict,
             (f'{fetch.days_since(pr["createdAt"])}d', "dim-right")]
    events = [(c["committedDate"], colored("dim", "commit")) for c in pr["commits"]] + [
        (r["submittedAt"], f'{state_label(r)} '
                           f'{escape(r["author"]["login"])}') for r in pr["reviews"]]
    tickets = [by_key[k] for k in sorted(g.ticket_keys_in(pr)) if k in by_key]
    lines = [heading(pr["title"]), "",
             field("pr", f'{link(pr["url"], f"{g.tui_repo(pr)}#{pr['number']}")} {colored("dim", "by")} {escape(pr["author"]["login"])} '
                         f'{colored("dim", "open")} {fetch.days_since(pr["createdAt"])}d'),
             field("review", escape(label) + (f' {colored("warn", "review requested")}' if pr["reviewRequests"] else "")),
             field("ci", pr["ci"]),
             field("merge", "conflicts" if pr["mergeable"] == "CONFLICTING" else "clean")]
    lines += [field("ticket", f'{link(config.settings.jira_browse + t["key"], t["key"])} {colored("dim", f"({t['status']})")} {escape(t["summary"])}')
              for t in tickets] or [field("ticket", "—")]
    lines += comments_field(pr)
    lines += ["", separator("activity")] + [f'{colored("dim", g.local_time(at))}  {what}' for at, what in sorted(events, reverse=True)[:10]]
    return Entry(cells, "\n".join(lines), pr["url"], pr["url"],
                 f'{pr["repo"]} {g.tui_repo(pr)} {pr["number"]} {pr["title"]} {pr["author"]["login"]}', pr)


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


def conversation_row(comment):
    row = Text("comment", COLORS["blue"])
    row.append("\n" + comment["author"]["login"])
    return preview(row, comment["body"])


def review_items(pr):
    reviews = [(r["submittedAt"], {"row": review_row(r), "place": f'{escape(r["author"]["login"])} {state_label(r)}', "hunk": None,
                                   "path": None, "comments": indented(r["body"]), "url": pr["url"]})
               for r in pr["reviews"] if r["body"].strip()]
    notes = [(c["createdAt"], {"row": conversation_row(c), "place": f'{escape(c["author"]["login"])} {colored("blue", "commented")}',
                               "hunk": None, "path": None, "url": c["url"],
                               "comments": [colored("dim", g.local_time(c["createdAt"])), *indented(c["body"])]})
             for c in pr.get("conversation", [])]
    items = [item for _, item in sorted(reviews + notes, key=lambda pair: pair[0])]
    for thread in pr.get("threads", []):
        comments = []
        for comment in thread["comments"]:
            comments += ["" if comments else None,
                         f'[b]{escape(comment["author"]["login"])}[/b] {colored("dim", g.local_time(comment["createdAt"]))}',
                         *indented(comment["body"])]
        items.append({"row": thread_row(thread), "place": thread_place(thread), "hunk": thread["comments"][0]["diffHunk"],
                      "path": thread["path"], "comments": [line for line in comments if line is not None],
                      "url": thread["comments"][0].get("url", pr["url"])})
    return items


def comments_field(pr):
    count = len(review_items(pr))
    return [field("comments", f"[{ACCENT} underline @click=app.open_review(0)]{count} · c to open[/]")] if count else []


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
        text.append(numbers, ACCENT if i == len(lines) - 1 else COLORS["dim"])
        text.append(sign, f"{DIFF_SIGNS[sign]} on {background}")
        code = Syntax("", lexer, theme="github-dark", background_color=background).highlight(line[1:])
        code.right_crop(1)
        text.append_text(code)
        text.append(" " * (width - len(line)), f"on {background}")
        old, new = old + (sign != "+"), new + (sign != "-")
    return text


def epic_entry(epic, tickets):
    done = sum(1 for t in tickets if t["column"] == "done")
    filled = round(20 * done / len(tickets)) if tickets else 0
    lines = [heading(epic["summary"]), "",
             field("epic", f'{link(config.settings.jira_browse + epic["key"], epic["key"])} {colored("dim", f"({epic['status']})")}'),
             field("owner", escape(epic["owner"])), field("done", f"{done}/{len(tickets)}")]
    for key, label, _ in fetch.COLUMNS:
        column = [t for t in tickets if t["column"] == key]
        if column and key != "done":
            lines += ["", separator(f"{label.lower()} ({len(column)})")]
            lines += [f'{link(config.settings.jira_browse + t["key"], t["key"])} {escape(t["summary"])} {colored("dim", t["assignee"])}' for t in column]
    bar = Text()
    bar.append("█" * filled, COLORS["ok"])
    bar.append("░" * (20 - filled), COLORS["dim"])
    return Entry([(epic["key"], ""), (bar, ""), (f"{done}/{len(tickets)}", "dim-right"), (epic["summary"], "")],
                 "\n".join(lines), config.settings.jira_browse + epic["key"], epic["key"], f'{epic["key"]} {epic["summary"]}')


def change_entry(change):
    found = re.search(r'href="([^"]+)"', change["text"])
    url = found.group(1) if found else ""
    text = g.plain(change["text"])
    lines = [heading(change["label"]), "", link(url, text) if url else escape(text), "", field("at", change["at"].replace("T", " "))]
    return Entry([(f'{change["at"][5:10]} {change["at"][11:16]}', "dim"), (change["label"].lower(), g.TUI_REVIEW.get(change["tone"], "dim")),
                  (text, "")],
                 "\n".join(lines), url, url, f'{text} {change["label"]}')


def entries(board):
    prs, by_key = board["prs"], board["by_key"]
    return {"attention": [attention_entry(*item) for item in board["attention"]],
            "prs": [pr_entry(pr, by_key) for pr in sorted(prs, key=lambda p: p["createdAt"])],
            "changes": [change_entry(c) for c in board["changes"]],
            "epics": [epic_entry(e, board["tickets_by_epic"][e["key"]]) for e in board["epics"]]}


def cell_row(entry, widths):
    text = Text(no_wrap=True, overflow="ellipsis")
    for (value, tone), width in zip(entry.cells, widths):
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
                Binding("enter", "screen.open", "open on GitHub")]


class ReviewScreen(ModalScreen):
    BINDINGS = [Binding("y", "copy", "copy link"), Binding("escape", "close", "close"), Binding("q", "close", show=False)]

    def __init__(self, pr, items, start):
        super().__init__()
        self.pr, self.items, self.start = pr, items, start

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
        self.query_one("#review").border_title = f'{g.tui_repo(self.pr)}#{self.pr["number"]} · {escape(self.pr["title"])}'
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

BOARD_ACTIONS = {"focus_box", "focus_filter", "clear_filter", "copy_current", "refresh", "open_review"}


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
            yield Button("save", id="config-save")
        yield Footer()

    def shown(self, name):
        if self.current is None:
            return ""
        value = getattr(self.current, name)
        return ", ".join(value) if isinstance(value, list) else value

    def on_button_pressed(self, event):
        self.action_save()

    def action_save(self):
        values = {name: self.query_one(f"#config-{name}", Input).value.strip() for name in config.FIELDS}
        missing = [CONFIG_FIELDS[name][0] for name, value in values.items() if not value]
        if missing:
            self.notify(f"Fill in every field: {', '.join(missing)}", severity="error", timeout=5)
            return
        values["team"] = values["team"].replace(",", " ").split()
        self.dismiss(config.Settings(**values))

    def check_action(self, action, parameters):
        return action != "cancel" or self.current is not None

    def action_cancel(self):
        self.dismiss(self.current)


class TarkonApp(App):
    TITLE = "Tarkon"
    AUTO_FOCUS = "Board"
    CSS = """
    Screen { background: #0d1117; color: #d1d9e0; }
    .masthead { height: 1; }
    .masthead #logo { height: 1; margin-right: 1; }
    .masthead Static { height: 1; }
    #top { padding: 0 1; margin-bottom: 1; color: #6e7a87; }
    #top .brand { color: #21cfac; text-style: bold; width: auto; }
    #status { width: 1fr; text-align: right; color: #21cfac; }
    .pane { height: 1fr; }
    .column { width: 1fr; height: 1fr; }
    #panel-attention, #panel-epics { height: auto; max-height: 12; }
    #list-attention, #list-epics { height: auto; }
    .panel { border: round #30363d; border-title-color: #21cfac; padding: 0 1; height: 1fr; width: 1fr; background: #0d1117; }
    .panel:focus-within { border: round #21cfac; }
    .filter { border: none; height: 1; padding: 0; background: #0d1117; color: #d1d9e0; margin-bottom: 1; }
    .filter:focus { border: none; background: #161b22; }
    Board { border: none; padding: 0; background: #0d1117; height: 1fr; text-wrap: nowrap; text-overflow: ellipsis; }
    Board:focus { border: none; }
    Board > .option-list--option-highlighted { background: #1f6feb40; text-style: none; }
    Board:focus > .option-list--option-highlighted { background: #1f6feb66; }
    Board > .option-list--option-hover { background: #161b22; }
    Board > .option-list--option-disabled { color: #6e7a87; }
    .empty { color: #6e7a87; }
    Footer { background: #161b22; }
    ConfigScreen { align: center middle; background: #0d1117; }
    #config { width: 72; height: auto; border: round #21cfac; padding: 1 2; background: #0d1117; }
    #config .brand { color: #21cfac; text-style: bold; }
    #config .masthead { margin-bottom: 1; }
    #config .label { color: #6e7a87; margin-top: 1; }
    #config Button { margin-top: 2; }
    ReviewScreen { align: center middle; background: #01040980; }
    #review { width: 94%; height: 90%; border: round #21cfac; border-title-color: #21cfac; border-title-style: bold;
              background: #0d1117; padding: 0 1; }
    #review-list { width: 34; height: 1fr; border: none; border-right: vkey #30363d; padding: 0; background: #0d1117;
                   text-wrap: nowrap; text-overflow: ellipsis; }
    #review-list > .option-list--option-highlighted { background: #1f6feb66; text-style: none; }
    #review-thread { width: 1fr; padding: 0 0 0 2; }
    #review-place { height: auto; margin: 1 0; }
    #review-diff-box { height: auto; max-height: 60%; border: round #30363d; background: #0d1117; overflow-x: auto; }
    #review-diff { width: auto; }
    #review-comments-box { height: 1fr; margin-top: 1; }
    """
    BINDINGS = [*(Binding(str(n), f"focus_box({n})", "boxes", key_display="1-4", show=n == 1) for n in NUMBERS.values()),
                Binding("slash", "focus_filter", "filter", key_display="/"),
                Binding("escape", "clear_filter", "clear", show=False),
                Binding("c", "open_review", "comments"),
                Binding("y", "copy_current", "copy"),
                Binding("r", "refresh", "refresh"),
                Binding("q", "quit", "quit")]

    def __init__(self, load=web.build, opener=open_in_browser, copier=pbcopy, clock=time.time, cache=CACHE,
                 config_path=config.PATH, edit_config=False):
        super().__init__()
        self.config_path, self.edit_config = config_path, edit_config
        self.load, self.opener, self.copier, self.clock, self.cache = load, opener, copier, clock, cache
        self.stamp = cache.with_name("last-refresh")
        self.refreshing = False
        self.last_refresh = None
        self.sections = {key: [] for key in SECTIONS}
        self.current_section = "attention"

    def compose(self) -> ComposeResult:
        with Horizontal(id="top", classes="masthead"):
            yield logo()
            yield Static("Tarkon", classes="brand")
            yield Static("loading…", id="status")
        with Horizontal(classes="pane"):
            with Vertical(classes="column"):
                for key in SECTIONS:
                    with Vertical(id=f"panel-{key}", classes="panel") as panel:
                        panel.border_title = f"[{NUMBERS[key]}] {SECTIONS[key][0]}"
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
        saved = json.loads(self.cache.read_text()) if self.cache.exists() else None
        if saved:
            self.show_board(saved["board"], saved["at"])
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

    @work(thread=True, exclusive=True, exit_on_error=False)
    def fetch(self, started):
        fetch.TODAY = dt.date.today()
        try:
            board = self.load()
        except Exception as error:
            self.call_from_thread(self.failed, error)
            return
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        self.cache.write_text(json.dumps({"at": started, "board": board}, default=str, ensure_ascii=False))
        self.call_from_thread(self.show_board, board, started)

    def failed(self, error):
        self.refreshing = False
        self.query_one("#status", Static).update(f"[{COLORS['bad']}]refresh failed[/]")
        message = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error)
        self.notify(message, title="Refresh failed", severity="error", timeout=10, markup=False)

    def show_board(self, board, at):
        self.refreshing = False
        self.sections = entries(board)
        for key in SECTIONS:
            self.query_one(f"#panel-{key}").border_title = f"[{NUMBERS[key]}] {SECTIONS[key][0]} {len(self.sections[key])}"
            self.fill(key)
        self.query_one("#status", Static).update(f"updated {dt.datetime.fromtimestamp(at):%H:%M}")
        self.current_board().focus()

    def current_board(self):
        return self.query_one(f"#list-{self.current_section}", Board)

    def board_focused(self, board):
        self.current_section = board.section
        self.show_detail(board)

    def fill(self, key):
        board = self.query_one(f"#list-{key}", Board)
        query = self.query_one(f"#filter-{key}", Input).value.lower()
        _, empty, widths = SECTIONS[key]
        board.clear_options()
        for i, entry in enumerate(self.sections[key]):
            if query not in entry.search.lower():
                continue
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

    def action_focus_box(self, number):
        self.query_one(f"#list-{list(SECTIONS)[number - 1]}", Board).focus()

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
        items = review_items(entry.pr) if entry and entry.pr else []
        if not items:
            self.notify("no review comments", timeout=2)
            return
        self.push_screen(ReviewScreen(entry.pr, items, index))

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
    TarkonApp(edit_config=edit_config).run()
