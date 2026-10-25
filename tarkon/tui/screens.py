import math
from pathlib import Path

from PIL import Image as PILImage
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Input, OptionList, Static
from textual.widgets.option_list import Option
from textual_image.renderable import Image as Renderable
from textual_image.renderable.sixel import Image as SixelRenderable
from textual_image.renderable.tgp import Image as TGPRenderable
from textual_image.widget import Image, get_cell_size

from .. import config
from .entries import diff_text, escape

LOGO = Path(__file__).parent.parent / "logo.png"
LOGO_BLACK = Path(__file__).parent.parent / "logo-black.png"
LOGO_WHITE = Path(__file__).parent.parent / "logo-white.png"
LOGO_ROWS = 1
# Without Sixel or Kitty graphics the logo falls back to half blocks, two pixels a row: unreadable at its size.
GRAPHICS = Renderable in (SixelRenderable, TGPRenderable)


def logo_image(rows, cell, path=LOGO):
    source = PILImage.open(path)
    columns = math.ceil(rows * cell.height * source.width / source.height / cell.width)
    image = PILImage.new("RGBA", (round(source.height * columns * cell.width / (rows * cell.height)), source.height))
    image.paste(source, ((image.width - source.width) // 2, 0))
    return image, columns


def logo(path=LOGO, rows=LOGO_ROWS, id="logo"):
    image, columns = logo_image(rows, get_cell_size(), path)
    widget = Image(image, id=id)
    widget.styles.width = columns
    return widget


class ThreadList(OptionList):
    BINDINGS = [Binding("j", "cursor_down", "thread", key_display="j/k"), Binding("k", "cursor_up", show=False),
                Binding("enter", "screen.open", "open")]


THEME_LABELS = {"default": "Default", "okuda": "LCARS Okuda · TNG and DS9", "picard": "LCARS Picard", "nerv": "NERV Magi",
                "eva01": "NERV - EVA 01"}


class ThemeScreen(ModalScreen):
    BINDINGS = [Binding("escape", "close", "close"), Binding("q", "close", show=False)]

    def __init__(self, current):
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="themes"):
            yield OptionList(*(Option(label, id=name) for name, label in THEME_LABELS.items()), id="theme-list")
        yield Footer()

    def on_mount(self):
        self.query_one("#themes").border_title = "theme"
        choices = self.query_one(OptionList)
        choices.highlighted = choices.get_option_index(self.current)
        choices.focus()

    def on_option_list_option_highlighted(self, event):
        event.stop()

    def on_option_list_option_selected(self, event):
        self.dismiss(event.option.id)

    def action_close(self):
        self.dismiss()


class DiffBox(VerticalScroll):
    # The diff wraps to the box's width, so it is drawn again whenever the box gets or changes its size.
    def on_resize(self):
        self.screen.show_diff()


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
                    with DiffBox(id="review-diff-box"):
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
        self.call_after_refresh(self.show_diff)
        self.query_one("#review-comments", Static).update("\n".join(item["comments"]))
        self.query_one("#review-comments-box").scroll_home(animate=False)

    def show_diff(self):
        item, box = self.current(), self.query_one("#review-diff-box")
        if item["hunk"] and box.scrollable_content_region.width:
            self.query_one("#review-diff", Static).update(diff_text(item["hunk"], item["path"], box.scrollable_content_region.width))
            self.call_after_refresh(box.scroll_end, animate=False)

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
                yield Static("TARKON config", classes="brand")
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
