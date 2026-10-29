"""The board's widgets: its boxes' lists and titles, and the LCARS sidebar buttons and tab pills."""

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import OptionList, Static

from . import frames, theme
from .boxes import BOXES, NUMBERS
from .frames import LCARS_NAMES
from .theme import COLORS

LEFT_CAP, RIGHT_CAP = "\ue0b6", "\ue0b4"
# NERV writes titles into the box line and outlines its tabs, after nerv-ui's labels and navigation.
# Cyberpunk slants its blocks and keeps its lines square, after the game's HUD.
TITLE_CAPS = {"lcars": (LEFT_CAP, RIGHT_CAP), "nerv": ("", ""), "cyberpunk": ("◢", "◤")}
TAB_CAPS = {"lcars": (LEFT_CAP, RIGHT_CAP), "nerv": ("▕", "▏"), "cyberpunk": ("◢", "◤")}
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
        super().__init__(f"{NUMBERS[key]:02d}\n{LCARS_NAMES.get(key, BOXES[key][0]).upper()}", id=f"side-{key}", classes="side")
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

    def on_resize(self):
        self.app.redraw(self.section)
