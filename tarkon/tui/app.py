import asyncio
import datetime as dt
import math
import subprocess
import threading
import time
from dataclasses import replace

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import ContentSwitcher, Footer, Input, OptionList, Static, Tab, Tabs
from textual.widgets.option_list import Option

from .. import config, rows
from ..adapters import paths, storage
from ..application.refresh import saved_board
from ..domain import changes
from ..domain.review import CONDITIONS, condition
from . import theme
from .entries import cell_row, entries, escape
from .screens import LOGO_BLACK, LOGO_WHITE, ConfigScreen, ReviewScreen, ThemeScreen, logo
from .system import leave, open_in_browser, pbcopy
from .theme import COLORS, use_theme

# A refresh costs about 5 s and at most 9 of GitHub's 5000 GraphQL points an hour.
REFRESH_SECONDS = 5 * 60
REFRESH_COOLDOWN = 30
CACHE = paths.CACHE_DIR / "cache.json"
PR_WIDTHS = [15, 9, 10, 17, 4, 10, 4]
# LCARS draws review, CI, conflict and days as padded pills, which need more room than their plain text.
LCARS_PR_WIDTHS = [15, 9, 10, 21, 6, 12, 8]
CHANGE_WIDTHS = [12, 18, None]
NO_CHANGES = f"no changes in the last {changes.CHANGES_HOURS} h"
SECTIONS = {"attention": ("attention", "nothing to flag", [2, None]),
            "prs": ("team prs", "no open prs", PR_WIDTHS),
            "changes": ("changes", NO_CHANGES, CHANGE_WIDTHS),
            "epics": ("epics", "no epics", [9, 20, 6, None]),
            "mine_prs": ("my prs", "no open prs", PR_WIDTHS),
            "mine_tickets": ("my tickets", "no open tickets", [10, None])}
LCARS_NAMES = {"prs": "crew reports", "changes": "captain's log"}
NERV_NAMES = {"attention": "emergency", "prs": "sorties", "changes": "operations log", "epics": "projects", "mine_prs": "my sorties",
              "mine_tickets": "my orders", "details": "magi analysis"}
FRAME_NAMES = {"lcars": LCARS_NAMES, "nerv": NERV_NAMES}
# Evangelion's blood types: orange for an unknown pattern, blue for an Angel.
NERV_CONDITIONS = {"green": "NORMAL", "yellow": "PATTERN ORANGE", "red": "PATTERN BLUE"}
# EVA 01 reads the level as Unit-01's sync with its pilot, and berserk when it breaks.
EVA_CONDITIONS = {"green": "SYNC STABLE", "yellow": "SYNC UNSTABLE", "red": "BERSERK"}
THEME_CONDITIONS = {"nerv": NERV_CONDITIONS, "eva01": EVA_CONDITIONS}
CONDITION_TONES = {"green": "ok", "yellow": "warn", "red": "bad"}
TABS = {"overview": ["attention", "prs", "changes", "epics"], "mine": ["mine_prs", "mine_tickets"]}
NUMBERS = {key: n for n, key in enumerate(SECTIONS, len(TABS) + 1)}
TAB_OF = {key: tab for tab, keys in TABS.items() for key in keys}
LEFT_CAP, RIGHT_CAP = "\ue0b6", "\ue0b4"
# NERV writes titles into the box line and outlines its tabs, after nerv-ui's labels and navigation.
TITLE_CAPS = {"lcars": (LEFT_CAP, RIGHT_CAP), "nerv": ("", "")}
TAB_CAPS = {"lcars": (LEFT_CAP, RIGHT_CAP), "nerv": ("▕", "▏")}
FRAME_EDGES = {"lcars": ("╭─", "─╮"), "nerv": ("┏━", "━┓")}
HAZARD_STRIPE = "◢◤" * 200
HEAVY_LINE = "━" * 400
# Star Trek's running in-joke number, drawn in blocks: a terminal cell cannot grow its font.
FORTY_SEVEN = "█ █ ███\n█ █   █\n███   █\n  █   █\n  █   █"


def widths(key):
    found = SECTIONS[key][2]
    return LCARS_PR_WIDTHS if found is PR_WIDTHS and theme.frame() else found


def section_name(key):
    default = SECTIONS[key][0] if key in SECTIONS else key
    return FRAME_NAMES.get(theme.frame(), {}).get(key, default)


def glyphs(table):
    return table[theme.frame() or "lcars"]


def seen_mark(change):
    return f'{change["at"]} {change["label"]}'


def panel_title(key, count):
    number, name = NUMBERS[key], section_name(key)
    title = f"{number:02d}-{name.upper()}" if theme.frame() else f"[{number}] {name}"
    return title if count is None else f"{title} {count}"


def elbow(color):
    """The LCARS corner joining the bar to the sidebar: a rounded outer corner, a fillet at the inner one and a panel code."""
    curve, fill = f"{color} on {COLORS['bg']}", f"bold {COLORS['title']} on {color}"
    return Text.assemble(("▗▄", curve), (" " * 11 + "\n" + " " * 12, fill), ("▘\n", curve), (" " * 12, fill), " \n", (" " * 12, fill), " \n",
                         (f"{'04-1701':^12}", fill), " ")


class SideButton(Static):
    def __init__(self, key):
        super().__init__(f"{NUMBERS[key]:02d}\n{LCARS_NAMES.get(key, SECTIONS[key][0]).upper()}", id=f"side-{key}", classes="side")
        self.key = key

    def on_click(self):
        self.app.action_focus_box(NUMBERS[self.key])


class TabPill(Horizontal):
    def __init__(self, number, tab):
        super().__init__(Static(LEFT_CAP, classes="cap"), Static(f" {number:02d} {tab.upper()} ", classes="seg"),
                         Static(RIGHT_CAP, classes="cap"), id=f"pill-{tab}", classes="tab-pill")
        self.number = number

    def on_click(self):
        self.app.action_focus_tab(self.number)


class PanelTitle(Horizontal):
    def __init__(self):
        super().__init__(Static("╭─", classes="edge"), Static(LEFT_CAP, classes="cap"), Static(classes="seg code"), Static(classes="name"),
                         Static(classes="seg fill"), Static(classes="seg count"), Static(RIGHT_CAP, classes="cap"), Static("─╮", classes="edge"),
                         classes="ptitle")

    def show(self, code, name, count):
        left_edge, left_cap, code_seg, name_seg, fill, count_seg, right_cap, right_edge = self.query(Static)
        nerv = theme.frame() == "nerv"
        for widget, glyph in zip((left_edge, right_edge, left_cap, right_cap), (*glyphs(FRAME_EDGES), *glyphs(TITLE_CAPS))):
            widget.update(glyph)
        fill.update(HEAVY_LINE if nerv else "")
        code_seg.update(f"■ {code}" if nerv and code else code)
        code_seg.display = bool(code)
        name_seg.update(name)
        count_seg.update(count)


class Board(OptionList):
    BINDINGS = [Binding("j", "cursor_down", show=False), Binding("k", "cursor_up", show=False),
                Binding("enter", "app.open_current", "open")]

    def __init__(self, section, **kwargs):
        super().__init__(**kwargs)
        self.section = section

    def on_focus(self):
        self.app.board_focused(self)

BOARD_ACTIONS = {"focus_tab", "focus_box", "focus_filter", "clear_filter", "copy_current", "refresh", "open_review", "pick_theme"}


class TarkonApp(App):
    TITLE = "TARKON"
    AUTO_FOCUS = "Board"
    CSS_PATH = "app.tcss"
    BINDINGS = [*(Binding(str(n), f"focus_tab({n})", "tabs", key_display="1-2", show=n == 1) for n in range(1, len(TABS) + 1)),
                *(Binding(str(n), f"focus_box({n})", "boxes", key_display="3-8", show=n == 3) for n in NUMBERS.values()),
                Binding("slash", "focus_filter", "filter", key_display="/"),
                Binding("escape", "clear_filter", "clear", show=False),
                Binding("c", "open_review", "comments"),
                Binding("y", "copy_current", "copy"),
                Binding("r", "refresh", "refresh"),
                Binding("t", "pick_theme", "theme"),
                Binding("q", "quit", "quit")]

    def __init__(self, collect=None, load=None, opener=open_in_browser, copier=pbcopy, clock=time.time, cache=CACHE,
                 config_path=config.PATH, edit_config=False):
        super().__init__()
        self.config_path, self.edit_config = config_path, edit_config
        self.load = load or (lambda: collect(self.settings))
        self.opener, self.copier, self.clock, self.cache = opener, copier, clock, cache
        self.stamp = cache.with_name("last-refresh")
        self.seen_path = cache.with_name("seen.json")
        self.seen = None
        self.news = {}
        self.passing = None
        self.refreshing = False
        self.last_refresh = None
        self.sections = {key: [] for key in SECTIONS}
        self.board = None
        self.settings = None
        self.updated_at = None
        self.refresh_failed = False
        self.current_section = "attention"
        self.level = None

    def get_css_variables(self):
        return {**super().get_css_variables(), **{f"mc-{name}": value for name, value in COLORS.items()}}

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Static(id="elbow")
            mark = logo(LOGO_BLACK, 2, "elbow-logo")
            mark.styles.offset = ((12 - int(mark.styles.width.value)) // 2, 1)
            yield mark
            with Vertical(id="header-main"):
                yield Static(id="bar")
                with Horizontal(id="top", classes="masthead"):
                    yield logo()
                    yield logo(LOGO_WHITE, id="nerv-logo")
                    yield Static("TARKON", classes="brand")
                    yield Static(id="condition")
                    yield Static("loading…", id="status")
                with Horizontal(id="pills"):
                    for n, tab in enumerate(TABS, 1):
                        yield TabPill(n, tab)
        yield Tabs(*(Tab(f"[{n}] {tab.capitalize()}", id=f"tab-{tab}") for n, tab in enumerate(TABS, 1)))
        with Horizontal(classes="pane"):
            with Vertical(id="sidebar"):
                for key in SECTIONS:
                    yield SideButton(key)
                yield Static(FORTY_SEVEN, id="side-fill")
            with ContentSwitcher(initial=f"pane-{next(iter(TABS))}", id="panes"):
                for tab, keys in TABS.items():
                    with Vertical(id=f"pane-{tab}"):
                        for key in keys:
                            with Vertical(id=f"panel-{key}", classes="panel") as panel:
                                panel.border_title = panel_title(key, None)
                                yield PanelTitle()
                                with Vertical(classes="pbody"):
                                    yield Input(placeholder="/ filter", id=f"filter-{key}", classes="filter")
                                    yield Board(key, id=f"list-{key}")
            with Vertical(id="panel-details", classes="panel") as panel:
                panel.border_title = "details"
                yield PanelTitle()
                with VerticalScroll(classes="pbody"):
                    yield Static(id="detail")
        with Horizontal(id="foot"):
            yield Static(id="footcap")
            yield Static(LEFT_CAP, id="foot-cap")
            yield Footer()

    def check_action(self, action, parameters):
        return not isinstance(self.screen, (ConfigScreen, ReviewScreen, ThemeScreen)) or action not in BOARD_ACTIONS

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
            self.show_board(saved_board(saved["board"]), saved["at"])
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
        status = {"lcars": rows.stardate(when), "nerv": f"MAGI · MELCHIOR BALTHASAR CASPER · SYNC {when:%H:%M}"}
        pilot = f"EVA-01 · PILOT {self.settings.github_user.upper()} · SYNC {when:%H:%M}"
        self.query_one("#status", Static).update(pilot if theme.current == "eva01" else status.get(theme.frame(), f"updated {when:%H:%M}"))

    def title_panels(self):
        for n, (tab, keys) in enumerate(TABS.items(), 1):
            dot = " ●" if any(entry.url in self.news for key in keys for entry in self.sections[key]) else ""
            self.query_one(f"#tab-{tab}", Tab).label = f"[{n}] {tab.capitalize()}{dot}"
            left, seg, right = self.query(f"#pill-{tab} Static")
            left.update(glyphs(TAB_CAPS)[0])
            right.update(glyphs(TAB_CAPS)[1])
            seg.update(f" {n:02d} {tab.upper()}{dot} ")
        for key in SECTIONS:
            new = sum(1 for entry in self.sections[key] if entry.url in self.news)
            count = (f"{len(self.sections[key])} · {new} new" if new else len(self.sections[key])) if self.board else None
            self.query_one(f"#panel-{key}").border_title = panel_title(key, count)
            self.query_one(f"#panel-{key} PanelTitle", PanelTitle).show(f"{NUMBERS[key]:02d}", section_name(key).upper(),
                                                                       "" if count is None else str(count))
        details = self.query_one("#panel-details")
        details.border_title = section_name("details").upper() if theme.frame() else "details"
        details.query_one(PanelTitle).show("", section_name("details").upper(), "")

    def fill_sections(self, board):
        self.board = board
        self.sections = entries(board, self.settings)
        self.find_news(board["changes"])
        self.level = condition(board["prs"], self.settings.github_user)
        tone = COLORS[CONDITION_TONES[self.level]]
        label = THEME_CONDITIONS.get(theme.current, CONDITIONS)[self.level]
        pill = Text.assemble((LEFT_CAP, tone), (f" {label} ", f"bold {COLORS['title']} on {tone}"), (RIGHT_CAP, tone))
        # NERV flags the level as a marked line, after nerv-ui's condition banner.
        flag = Text.assemble(("■ ", tone), (label, f"bold {tone}"))
        self.query_one("#condition", Static).update(flag if theme.frame() == "nerv" else pill)
        self.paint_frame()
        self.title_panels()
        for key in SECTIONS:
            self.fill(key)

    def find_news(self, changes):
        """The changes not seen yet, by item; the first run takes every change as seen."""
        saved = storage.read(self.seen_path) if self.seen is None else {"seen": self.seen}
        current = {change["item"]: change for change in changes}
        self.seen = {item: mark for item, mark in saved["seen"].items() if item in current} if saved else \
            {item: seen_mark(change) for item, change in current.items()}
        if not saved:
            storage.write(self.seen_path, {"seen": self.seen})
        self.news = {item: change for item, change in current.items() if self.seen.get(item) != seen_mark(change)}

    def pass_by(self, url):
        if self.passing in self.news and self.passing != url:
            self.mark_seen(self.passing)
        self.passing = url

    def mark_seen(self, url):
        self.seen[url] = seen_mark(self.news.pop(url))
        storage.write(self.seen_path, {"seen": self.seen})
        for key in SECTIONS:
            board = self.query_one(f"#list-{key}", Board)
            for index in range(board.option_count):
                option_id = board.get_option_at_index(index).id
                if option_id and self.sections[key][int(option_id)].url == url:
                    board.replace_option_prompt_at_index(index, self.row(key, self.sections[key][int(option_id)]))
        self.title_panels()

    def row(self, key, entry):
        return Text.assemble(("● ", COLORS["accent"]) if entry.url in self.news else "  ", cell_row(entry, widths(key)))

    def apply_theme(self, name):
        use_theme(name)
        self.set_class(bool(theme.frame()), "framed")
        self.set_class(theme.lcars(), "lcars")
        self.set_class(theme.frame() == "nerv", "nerv")
        self.set_class(theme.current == "eva01", "eva01")
        self.refresh_css()
        self.paint_frame()
        self.title_panels()
        if self.updated_at and not self.refreshing and not self.refresh_failed:
            self.show_updated()

    def paint_frame(self):
        red = self.level == "red"
        color = COLORS["bad" if red else "accent"]
        bar = self.query_one("#bar", Static)
        bar.set_class(red, "-red")
        stripe = Text(HAZARD_STRIPE if theme.frame() == "nerv" else RIGHT_CAP, f"{color} on {COLORS['bg']}")
        if theme.current == "eva01" and not red:
            # EVA 01 keeps the top quiet and saves the hazard stripe for an alarm.
            stripe = Text(HEAVY_LINE, f"{COLORS['line']} on {COLORS['bg']}")
        bar.update(stripe)
        self.query_one("#elbow", Static).update(elbow(color))
        self.query_one("#elbow-logo").styles.background = color

    def action_pick_theme(self):
        self.push_screen(ThemeScreen(self.settings.theme), self.theme_picked)

    def theme_picked(self, name):
        if name is None:
            return
        found = replace(self.settings, theme=name)
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
        empty = SECTIONS[key][1]
        board.clear_options()
        shown = [(i, entry) for i, entry in enumerate(self.sections[key]) if query in entry.search.lower()]
        group = None
        for i, entry in shown:
            if entry.group and entry.group != group:
                group = entry.group
                size = sum(1 for _, other in shown if other.group == group)
                board.add_option(Option(Text(f"── {group} ({size}) ──", COLORS["dim"]), disabled=True))
            board.add_option(Option(self.row(key, entry), id=str(i)))
        if not self.sections[key]:
            board.add_option(Option(Text(empty, COLORS["dim"]), disabled=True))
        first = next((i for i in range(board.option_count) if not board.get_option_at_index(i).disabled), None)
        # A rebuild moves the cursor to the first row: that is not the reader passing by.
        if key == self.current_section:
            self.passing = None
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
        self.pass_by(entry.url if entry else None)
        news = self.news.get(entry.url) if entry else None
        heading = f'[{COLORS["accent"]}]● {escape(news["label"])} · {news["at"][11:16]}[/]\n\n' if news else ""
        self.query_one("#detail", Static).update(heading + entry.detail if entry else "")

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
        for pill in self.query(TabPill):
            pill.set_class(pill.id == f"pill-{tab}", "-on")
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


def main(collect, edit_config=False):
    app = TarkonApp(collect, edit_config=edit_config)
    app.run()
    leave(app)
