import asyncio
import datetime as dt
import math
import os
import threading
import time
from dataclasses import replace

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import ContentSwitcher, Footer, Input, Static, Tab, Tabs
from textual.widgets.option_list import Option

from .. import config
from ..adapters import storage
from ..application.refresh import saved_board
from ..domain import changes
from ..domain.review import condition
from ..domain.snoozes import asleep, awake, change_marks
from . import frames, notifiers, screens, theme
from .board_files import (CACHE, KEPT_UPGRADES, REFRESH_COOLDOWN, REFRESH_SECONDS, SNOOZABLE, last_started, mark_start, page,
                          read_snoozed, refresh_mark, save_board, snoozes, write_page)
from .boxes import ASIDE, BOXES, LCARS_PR_WIDTHS, MIN_TITLE, NUMBERS, TAB_NUMBERS, TAB_OF, TABS, panel_title, section_name, widths
from .entries import cell_row, entries, escape, factory_entry, ticket_entry
from .screens import LOGO_BLACK, LOGO_WHITE, ConfigScreen, ReviewScreen, ThemeScreen, TicketScreen, logo
from .system import error_message, leave, off_loop, open_in_browser, pbcopy
from .theme import COLORS, use_theme
from .widgets import (FORTY_SEVEN, HATCHED_LINE, HAZARD_STRIPE, HEAVY_LINE, LEFT_CAP, RIGHT_CAP, TAB_CAPS, TITLE_CAPS, Board,
                      PanelTitle, SideButton, TabPill, elbow, glyphs)

FACTORY_SECONDS = 10
REFRESHING = {"lcars": "ENGAGING WARP DRIVE…", "cyberpunk": "JACKING IN…"}
CONDITION_TONES = {"green": "ok", "yellow": "warn", "red": "bad"}
BOARD_ACTIONS = {"focus_tab", "focus_box", "focus_filter", "clear_filter", "copy_current", "refresh", "open_review", "view_ticket", "pick_theme",
                 "snooze", "wake_snoozed", "focus_session"}


class MagiApp(App):
    TITLE = "MAGI"
    AUTO_FOCUS = "Board"
    CSS_PATH = "app.tcss"
    BINDINGS = [*(Binding(str(n), f"focus_tab({n})", "tabs", key_display="1-2", show=n == 1) for n in range(1, len(TABS) + 1)),
                *(Binding(str(n), f"focus_box({n})", "boxes", key_display="3-9", show=n == 3) for n in NUMBERS.values()),
                Binding("slash", "focus_filter", "filter", key_display="/"),
                Binding("escape", "clear_filter", "clear", show=False),
                Binding("c", "open_review", "comments"),
                Binding("v", "view_ticket", "ticket"),
                Binding("y", "copy_current", "copy"),
                Binding("g", "focus_session", "session", show=False),
                Binding("s", "snooze", "snooze"),
                Binding("S", "wake_snoozed", "wake", show=False),
                Binding("r", "refresh", "refresh"),
                Binding("t", "pick_theme", "theme"),
                Binding("q", "quit", "quit")]

    def __init__(self, collect=None, load=None, fetch_ticket=None, factory=list, focus_session=None, opener=open_in_browser, copier=pbcopy, clock=time.time, cache=CACHE,
                 config_path=config.PATH, edit_config=False, notifier=notifiers.Silent()):
        super().__init__()
        self.notifier, self.watching = notifier, False
        self.config_path, self.edit_config = config_path, edit_config
        self.load = load or (lambda: collect(self.settings))
        self.fetch_ticket, self.loading_ticket = fetch_ticket, None
        self.factory, self.factory_tickets, self.reading_factory = factory, [], False
        self.focus_session = focus_session
        # The factory rows last drawn: None until the box is first drawn, so an empty factory still says so.
        self.factory_drawn = None
        self.opener, self.copier, self.clock, self.cache = opener, copier, clock, cache
        self.stamp = refresh_mark(cache)
        self.seen_path = cache.with_name("seen.json")
        self.seen = None
        self.snoozed_path = snoozes(cache)
        self.snoozed = None
        self.hidden = {}
        self.news = {}
        self.passing = None
        self.refreshing = False
        self.last_refresh = None
        self.sections = {key: [] for key in BOXES}
        self.board = None
        # The boxes read at least once: only those show a count, and the factory is read apart from the board.
        self.counted = set()
        self.settings = None
        self.updated_at = None
        self.refresh_failed = False
        self.current_section = next(iter(BOXES))
        self.level = None

    def get_css_variables(self):
        return {**super().get_css_variables(), **{f"tk-{name}": value for name, value in COLORS.items()}}

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
                    yield Static("MAGI", classes="brand")
                    yield Static(id="condition")
                    yield Input(placeholder="/ filter", id="filter")
                    yield Static("loading…", id="status")
                with Horizontal(id="pills"):
                    for tab, n in TAB_NUMBERS.items():
                        yield TabPill(n, tab)
        yield Tabs(*(Tab(f"[{n}] {tab.capitalize()}", id=f"tab-{tab}") for tab, n in TAB_NUMBERS.items()))
        with Horizontal(classes="pane"):
            with Vertical(id="sidebar"):
                for key in BOXES:
                    yield SideButton(key)
                yield Static(FORTY_SEVEN, id="side-fill")
            with ContentSwitcher(initial=f"pane-{next(iter(TABS))}", id="panes"):
                for tab, keys in TABS.items():
                    with Vertical(id=f"pane-{tab}"):
                        for key in keys:
                            yield from self.box(key)
            with Vertical(id="aside"):
                with Vertical(id="panel-details", classes="panel") as panel:
                    panel.border_title = "details"
                    yield PanelTitle()
                    with VerticalScroll(classes="pbody"):
                        yield Static(id="detail")
                for key in ASIDE:
                    yield from self.box(key)
        with Horizontal(id="foot"):
            yield Static(id="footcap")
            yield Static(LEFT_CAP, id="foot-cap")
            yield Footer()

    def box(self, key):
        with Vertical(id=f"panel-{key}", classes="panel") as panel:
            panel.border_title = panel_title(key, None)
            yield PanelTitle()
            with Vertical(classes="pbody"):
                yield Board(key, id=f"list-{key}")

    def check_action(self, action, parameters):
        return not isinstance(self.screen, (ConfigScreen, ReviewScreen, ThemeScreen, TicketScreen)) or action not in BOARD_ACTIONS

    def on_mount(self):
        self.set_class(not screens.GRAPHICS, "no-graphics")
        found = config.load(self.config_path)
        # The saved theme may since have been dropped.
        self.saved = found and replace(found, theme=theme.offered(found.theme))
        if self.saved is None or self.edit_config:
            self.push_screen(ConfigScreen(self.saved), self.configured)
        else:
            self.start(self.saved)

    def configured(self, found):
        config.save(found, self.config_path)
        self.start(found, force=found != self.saved)

    def start(self, found, force=False):
        self.settings = found
        self.apply_theme(found.theme)
        saved = storage.read(self.cache)
        if saved:
            self.show_board(saved_board(saved["board"]), saved["at"])
        self.last_refresh = last_started(saved, self.stamp)
        wait = 0 if self.last_refresh is None else self.last_refresh + REFRESH_COOLDOWN - self.clock()
        if force or wait <= 0:
            self.start_refresh()
        elif not saved:
            self.query_one("#status", Static).update(f"next refresh in {math.ceil(wait)}s")
            self.set_timer(wait, self.start_refresh)
        self.set_interval(REFRESH_SECONDS, self.start_refresh)
        self.read_factory()
        self.set_interval(FACTORY_SECONDS, self.read_factory)

    def read_factory(self):
        # One read at a time: a herdr that hangs must not pile up threads.
        if not self.reading_factory:
            self.reading_factory = True
            self.fetch_factory()

    @work(group="factory", exit_on_error=False)
    async def fetch_factory(self):
        found, error = await off_loop(self.factory)
        self.reading_factory = False
        # A factory that cannot be read keeps what it showed: it never stops the board.
        if not error:
            self.factory_tickets = found
            self.show_factory()

    def show_factory(self):
        rows = self.factory_rows()
        if rows == self.factory_drawn:
            return
        board = self.query_one("#list-factory", Board)
        kept = self.entry(board)
        self.sections["factory"] = self.factory_drawn = rows
        self.counted.add("factory")
        self.title_panels()
        self.fill("factory", kept)

    def factory_rows(self):
        now = dt.datetime.fromtimestamp(self.clock(), dt.timezone.utc)
        return [factory_entry(ticket, now, self.settings, self.board) for ticket in self.factory_tickets]

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
        mark_start(self.stamp, self.last_refresh)
        self.query_one("#status", Static).update(REFRESHING.get(theme.frame(), "refreshing…"))
        self.fetch(self.last_refresh)

    @work(exclusive=True, exit_on_error=False)
    async def fetch(self, started):
        # Off the loop on a daemon thread: quitting must not wait for acli and gh to finish.
        board, error = await off_loop(self.load)
        if error:
            self.failed(error)
            return
        save_board(self.cache, started, board)
        # The refresh that starts a session tells nothing: what is news is what arrives while Magi runs.
        known = self.news_marks() if self.watching else None
        self.watching = True
        self.show_board(board, started)
        if known is not None and self.news_marks() - known:
            await asyncio.to_thread(self.notifier.news)

    def news_marks(self):
        return {(item, changes.change_mark(change)) for item, change in self.news.items()}

    def on_unmount(self):
        self.notifier.leave()

    def failed(self, error):
        self.refreshing = False
        self.refresh_failed = True
        self.query_one("#status", Static).update(f"[{COLORS['bad']}]refresh failed[/]")
        self.notify(error_message(error), title="Refresh failed", severity="error", timeout=10, markup=False)

    def show_board(self, board, at):
        self.refreshing = False
        self.fill_sections(board)
        self.updated_at = at
        self.refresh_failed = False
        self.show_updated()
        self.write_page()
        self.current_board().focus()

    def show_updated(self):
        when = dt.datetime.fromtimestamp(self.updated_at)
        self.query_one("#status", Static).update(frames.status(theme.current, when, self.settings.github_user))

    def title_panels(self):
        for tab, keys in TABS.items():
            n = TAB_NUMBERS[tab]
            dot = " ●" if any(entry.url in self.news for key in keys for entry in self.sections[key]) else ""
            self.query_one(f"#tab-{tab}", Tab).label = f"[{n}] {tab.capitalize()}{dot}"
            left, seg, right = self.query(f"#pill-{tab} Static")
            left.update(glyphs(TAB_CAPS)[0])
            right.update(glyphs(TAB_CAPS)[1])
            seg.update(f" {n:02d} {tab.upper()}{dot} ")
        for key in BOXES:
            new = sum(1 for entry in self.sections[key] if entry.url in self.news)
            snoozed = self.hidden.get(key, 0)
            count = " · ".join([str(len(self.sections[key]))] + [f"{new} new"] * bool(new) + [f"{snoozed} snoozed"] * bool(snoozed)) \
                if key in self.counted else None
            self.query_one(f"#panel-{key}").border_title = panel_title(key, count)
            self.query_one(f"#panel-{key} PanelTitle", PanelTitle).show(f"{NUMBERS[key]:02d}", section_name(key).upper(),
                                                                       "" if count is None else str(count))
        details = self.query_one("#panel-details")
        details.border_title = section_name("details").upper() if theme.frame() else "details"
        details.query_one(PanelTitle).show("", section_name("details").upper(), "")

    def fill_sections(self, board):
        kept = {key: self.entry(self.query_one(f"#list-{key}", Board)) for key in BOXES}
        self.board = board
        self.sections = {**entries(board, self.settings), "factory": self.factory_rows()}
        self.factory_drawn = self.sections["factory"]
        self.counted.update(self.sections)
        self.hide_snoozed(board["changes"])
        self.find_news(board["changes"])
        self.level = condition(board["prs"], self.settings.github_user)
        tone = COLORS[CONDITION_TONES[self.level]]
        label = frames.condition_label(theme.current, self.level)
        left, right = glyphs(TITLE_CAPS)
        pill = Text.assemble((left, tone), (f" {label} ", f"bold {COLORS['title']} on {tone}"), (right, tone))
        # NERV flags the level as a marked line, after nerv-ui's condition banner.
        flag = Text.assemble(("■ ", tone), (label, f"bold {tone}"))
        self.query_one("#condition", Static).update(flag if theme.frame() == "nerv" else pill)
        self.paint_frame()
        self.title_panels()
        for key in BOXES:
            self.fill(key, kept[key])

    def find_news(self, found):
        """The changes not seen yet, by item; the first run takes every change as seen."""
        saved = storage.read(self.seen_path, KEPT_UPGRADES) if self.seen is None else {"seen": self.seen}
        current = {change["item"]: change for change in changes.latest(found, "item")}
        self.seen = {item: mark for item, mark in saved["seen"].items() if item in current} if saved else \
            {item: changes.change_mark(change) for item, change in current.items()}
        if not saved:
            storage.write(self.seen_path, {"seen": self.seen})
        self.news = {item: change for item, change in current.items() if self.seen.get(item) != changes.change_mark(change)}

    def hide_snoozed(self, found):
        """Snoozed items leave their box until they change; a snooze that woke up is dropped."""
        saved = self.snoozed or read_snoozed(self.snoozed_path)
        self.snoozed = {key: asleep(saved[key], found, {entry.url for entry in self.sections[key]}) for key in SNOOZABLE}
        if self.snoozed != saved:
            storage.write(self.snoozed_path, {"snoozed": self.snoozed})
        for key in SNOOZABLE:
            shown = awake(self.sections[key], self.snoozed[key], found)
            self.hidden[key] = len(self.sections[key]) - len(shown)
            self.sections[key] = shown

    def action_snooze(self):
        entry = self.current()
        if self.current_section not in SNOOZABLE:
            self.notify("only team prs snooze", timeout=2)
        elif entry:
            self.snoozed[self.current_section][entry.url] = change_marks(self.board["changes"]).get(entry.url)
            self.snoozes_changed()
            self.notify("snoozed until it changes", timeout=2)

    def action_wake_snoozed(self):
        if self.board and self.current_section in SNOOZABLE and self.snoozed[self.current_section]:
            self.snoozed[self.current_section] = {}
            self.snoozes_changed()

    def snoozes_changed(self):
        storage.write(self.snoozed_path, {"snoozed": self.snoozed})
        self.fill_sections(self.board)
        self.write_page()

    def write_page(self):
        # The page is an extra view of the board: failing to write it is told, never a reason to lose the board.
        try:
            write_page(page(self.cache), self.board, self.settings, self.snoozed, self.updated_at)
        except OSError as error:
            self.notify(f"web page not written: {error}", severity="warning", timeout=5, markup=False)

    def pass_by(self, url):
        if self.passing in self.news and self.passing != url:
            self.mark_seen(self.passing)
        self.passing = url

    def mark_seen(self, url):
        self.seen[url] = changes.change_mark(self.news.pop(url))
        storage.write(self.seen_path, {"seen": self.seen})
        for key in BOXES:
            board = self.query_one(f"#list-{key}", Board)
            for index in range(board.option_count):
                option_id = board.get_option_at_index(index).id
                if option_id and self.sections[key][int(option_id)].url == url:
                    board.replace_option_prompt_at_index(index, self.row(key, self.sections[key][int(option_id)]))
        self.title_panels()

    def row(self, key, entry):
        room = self.query_one(f"#list-{key}", Board).scrollable_content_region.width - 2
        return Text.assemble(("● ", COLORS["accent"]) if entry.url in self.news else "  ", cell_row(entry, widths(key, room)))

    def redraw(self, key):
        """A box that changes width redraws its rows, so a PR's title fills the room it has."""
        board = self.query_one(f"#list-{key}", Board)
        for index in range(board.option_count):
            option_id = board.get_option_at_index(index).id
            if option_id:
                board.replace_option_prompt_at_index(index, self.row(key, self.sections[key][int(option_id)]))

    def apply_theme(self, name):
        use_theme(name)
        self.set_class(bool(theme.frame()), "framed")
        self.set_class(theme.lcars(), "lcars")
        self.set_class(theme.frame() == "nerv", "nerv")
        self.set_class(theme.current == "eva01", "eva01")
        self.set_class(theme.frame() == "cyberpunk", "cyberpunk")
        # A PR row's pills need more room than half the screen: the new mark, the cells and their gaps, the box's border and padding.
        self.query_one("#panes").styles.min_width = 2 + MIN_TITLE + sum(filter(None, LCARS_PR_WIDTHS)) + len(LCARS_PR_WIDTHS) + 4 if theme.frame() else None
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
        top = {"nerv": HAZARD_STRIPE, "cyberpunk": HATCHED_LINE}.get(theme.frame(), RIGHT_CAP)
        stripe = Text(top, f"{color} on {COLORS['bg']}")
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

    def fill(self, key, kept=None):
        board = self.query_one(f"#list-{key}", Board)
        query = self.query_one("#filter", Input).value.lower()
        empty = BOXES[key][1]
        board.clear_options()
        shown = [(i, entry) for i, entry in enumerate(self.sections[key]) if query in entry.search.lower()]
        group = None
        for i, entry in shown:
            if entry.group and entry.group != group:
                if group:
                    board.add_option(Option(Text(""), disabled=True))
                group = entry.group
                size = sum(1 for _, other in shown if other.group == group)
                board.add_option(Option(Text(f"── {group} ({size}) ──", f"bold {COLORS['fg']}"), disabled=True))
            board.add_option(Option(self.row(key, entry), id=str(i)))
        if not self.sections[key]:
            board.add_option(Option(Text(empty, COLORS["dim"]), disabled=True))
        first = next((i for i in range(board.option_count) if not board.get_option_at_index(i).disabled), None)
        # A refresh keeps the row you were on while its item is still on the board.
        same = next((i for i in range(board.option_count) if kept and board.get_option_at_index(i).id
                     and self.sections[key][int(board.get_option_at_index(i).id)].copy == kept.copy), first)
        # A rebuild moves the cursor: that is not the reader passing by.
        if key == self.current_section:
            self.passing = None
        board.highlighted = same
        self.show_detail(board)

    def entry(self, board):
        option = board.highlighted_option
        return self.sections[board.section][int(option.id)] if option and option.id else None

    def current(self):
        return self.entry(self.current_board())

    def show_detail(self, board):
        # A highlight posted while the app quits can arrive after the details are gone.
        if self.current_section != board.section or not self.is_running:
            return
        entry = self.entry(board)
        self.pass_by(entry.url if entry else None)
        news = self.news.get(entry.url) if entry else None
        heading = f'[{COLORS["accent"]}]● {escape(news["label"])} · {news["at"][11:16]}[/]\n\n' if news else ""
        self.query_one("#detail", Static).update(heading + entry.detail if entry else "")

    def on_option_list_option_highlighted(self, event):
        self.show_detail(event.option_list)

    @on(Input.Changed, "#filter")
    def filter_changed(self):
        # Only the boxes already loaded: one still loading would draw its empty message.
        for key in BOXES.keys() & self.counted:
            self.fill(key, self.entry(self.query_one(f"#list-{key}", Board)))

    @on(Input.Submitted, "#filter")
    def filter_submitted(self):
        self.current_board().focus()

    def action_focus_tab(self, number):
        tab = next(tab for tab, n in TAB_NUMBERS.items() if n == number)
        if TAB_OF.get(self.current_section) != tab:
            self.action_focus_box(NUMBERS[TABS[tab][0]])

    def action_focus_box(self, number):
        key = list(BOXES)[number - NUMBERS[next(iter(BOXES))]]
        if key in TAB_OF:
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
        if TAB_OF.get(self.current_section) != tab:
            self.query_one(f"#list-{TABS[tab][0]}", Board).focus()

    def action_focus_filter(self):
        self.query_one("#filter", Input).focus()

    def action_clear_filter(self):
        self.query_one("#filter", Input).value = ""
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

    def action_focus_session(self):
        entry = self.current()
        if self.current_section != "factory" or not entry:
            return
        pane = next((ticket.pane for ticket in self.factory_tickets if ticket.key == entry.copy), None)
        if pane:
            # A daemon thread, as for the refresh: a herdr that hangs must not hold the board.
            threading.Thread(target=self.focus_session, args=(pane,), daemon=True).start()

    def action_view_ticket(self):
        entry = self.current()
        key = entry and entry.ticket
        if not key:
            self.notify("no ticket", timeout=2)
        elif key != self.loading_ticket:
            self.loading_ticket = key
            self.notify(f"loading {key}…", timeout=2)
            # A daemon thread, as for the refresh: quitting must not wait for acli.
            threading.Thread(target=self.load_ticket, args=(key,), daemon=True).start()

    def load_ticket(self, key):
        try:
            ticket = self.fetch_ticket(key)
            show = lambda: self.show_ticket(ticket)
        except Exception as error:
            message = error_message(error)
            show = lambda: self.notify(message, title=f"{key} failed", severity="error", timeout=10, markup=False)
        try:
            self.call_from_thread(self.ticket_loaded, show)
        except RuntimeError:  # the app quit and closed its loop while acli ran
            pass

    def ticket_loaded(self, show):
        self.loading_ticket = None
        show()

    def show_ticket(self, ticket):
        # A popup opened while Jira answered keeps its place; the next v opens the ticket at once.
        if len(self.screen_stack) == 1:
            self.push_screen(TicketScreen(ticket_entry(ticket, self.board["prs"], self.settings)))

    def action_open_link(self, url):
        self.opener(url)

    def action_copy_current(self):
        entry = self.current()
        if entry:
            self.action_copy_text(entry.copy)

    def action_copy_text(self, text):
        self.copier(text)
        self.notify(f"copied {text}", timeout=2)



def main(collect, fetch_ticket, factory=list, focus_session=None, edit_config=False):
    app = MagiApp(collect, fetch_ticket=fetch_ticket, factory=factory, focus_session=focus_session, edit_config=edit_config,
                  notifier=notifiers.notifier(os.environ))
    app.run()
    leave(app)
