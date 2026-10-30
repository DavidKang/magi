"""The board's widgets: its boxes' lists and titles, the details body, the LCARS sidebar buttons and the thin scrollbar."""

from rich.segment import Segment, Segments
from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.scrollbar import ScrollBar, ScrollBarRender
from textual.widgets import OptionList, Static

from . import frames, theme
from .boxes import BOXES, DIGITS
from .entries import fitted
from .frames import LCARS_NAMES
from .theme import COLORS

LEFT_CAP, RIGHT_CAP = "\ue0b6", "\ue0b4"
# NERV writes titles into the box line, after nerv-ui's labels.
# Cyberpunk slants its blocks and keeps its lines square, after the game's HUD.
TITLE_CAPS = {"lcars": (LEFT_CAP, RIGHT_CAP), "nerv": ("", ""), "cyberpunk": ("◢", "◤")}
FRAME_EDGES = {"lcars": ("╭─", "─╮"), "nerv": ("┏━", "━┓"), "cyberpunk": ("┌─", "─┐")}
HAZARD_STRIPE = "◢◤" * 200
HATCHED_LINE = "╱" * 400
HEAVY_LINE = "━" * 400
# Star Trek's running in-joke number, drawn in blocks: a terminal cell cannot grow its font.
FORTY_SEVEN = "█ █ ███\n█ █   █\n███   █\n  █   █\n  █   █"


def glyphs(table):
    return table[theme.frame() or "lcars"]


def elbow(color):
    """The LCARS corner joining the bar to the sidebar: a rounded outer corner, a fillet at the inner one and a panel code."""
    curve, fill = f"{color} on {COLORS['bg']}", f"bold {COLORS['title']} on {color}"
    return Text.assemble(("▗▄", curve), (" " * 11 + "\n" + " " * 12, fill), ("▘\n", curve), (" " * 12, fill), " \n", (" " * 12, fill), " \n",
                         (f"{frames.PANEL_CODE:^12}", fill), " ")


class SideButton(Static):
    def __init__(self, key):
        super().__init__(f"{DIGITS[key]:02d}\n{LCARS_NAMES.get(key, BOXES[key][0]).upper()}", id=f"side-{key}", classes="side")
        self.key = key

    def on_click(self):
        self.app.action_focus_box(DIGITS[self.key])


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


class ThinScrollBar(ScrollBarRender):
    """A vertical scrollbar drawn as half a cell, since a terminal cell is the narrowest a bar can be."""

    @classmethod
    def render_bar(cls, size=25, virtual_size=50, window_size=20, position=0, thickness=1, vertical=True, back_color=None, bar_color=None):
        if not vertical or not (window_size and size and virtual_size and size != virtual_size):
            return super().render_bar(size, virtual_size, window_size, position, thickness, vertical, back_color, bar_color)
        thumb = max(1, round(size * window_size / virtual_size))
        start = round((size - thumb) * position / (virtual_size - window_size))
        above, below = (Segment(" ", Style(bgcolor=back_color, meta={"@mouse.down": action})) for action in ("scroll_up", "scroll_down"))
        line = Segment("▐", Style(color=bar_color, bgcolor=back_color, meta={"@mouse.down": "grab"}))
        return Segments([above] * start + [line] * thumb + [below] * (size - start - thumb), new_lines=True)


ScrollBar.renderer = ThinScrollBar


class DetailBody(VerticalScroll):
    """The details box's body: an entry's detail, its description cut to what the box holds whenever the box changes size."""

    detail, fold, shown = "", 0, None

    def compose(self):
        yield Static(id="detail")

    def show(self, detail, fold):
        self.detail, self.fold = detail, fold
        self.fit()

    def on_resize(self):
        self.fit()

    def fit(self):
        # A fitted description leaves no scrollbar, so it wraps at the full width, not the one the last detail's scrollbar left.
        width, height = self.content_region.size
        # Before its first layout the box has no width to wrap at; the resize that lays it out fits it.
        shown = fitted(self.detail, self.fold, width, height) if width else self.detail
        # A refresh, a filter keystroke or a resize often fits the same text again; laying it out again would change nothing.
        if shown != self.shown:
            self.shown = shown
            self.query_one("#detail", Static).update(shown)


class Board(OptionList):
    BINDINGS = [Binding("j", "cursor_down", show=False), Binding("k", "cursor_up", show=False),
                Binding("enter", "app.open_current", "open")]

    def __init__(self, section, **kwargs):
        super().__init__(**kwargs)
        self.section = section

    def on_focus(self):
        self.app.board_focused(self)

    def on_resize(self):
        self.app.redraw(self.section)
