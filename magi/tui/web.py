"""The board as a web page the TUI writes after each refresh: built from the cache only, in a theme the page picks for itself."""

import ast
import datetime as dt
import json
import re
from pathlib import Path
from string import Template

from rich.text import Text
from textual.content import Content

from ..domain.review import condition
from ..domain.snoozes import awake
from . import frames, theme
from .entries import KEY_HINTS, entries, folded, shade
from .theme import FRAMES, THEMES
from .web_themes import JAPANESE, esc, faces, named, pieces, worded

# Tailwind's browser build: Magi has no node toolchain to compile the css ahead. The hash pins the file, so a changed one never runs.
TAILWIND = "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.1.4/dist/index.global.js"
TAILWIND_HASH = "sha384-ire6tt7Y6e2HMB3Q+cZpObkqM8M2DVZO9LimwpwuDZstD6FxU2vhSkUzEBlAX3dh"
TONES = ("ok", "bad", "warn", "blue", "dim", "accent")
# The page shows a long description's first lines; the TUI fits as many as its details box holds.
DESCRIPTION_LINES = 12
# A cell's kind after its tone, as the TUI names it: dim-right, warn-pill, bad-alarm.
KINDS = {"pill": "pill rounded-full border px-2 text-xs uppercase", "alarm": "font-bold uppercase"}
LEVELS = {"green": "ok", "yellow": "warn", "red": "bad"}
# The details are built in the default theme, so each colour in them reads back as the tone it came from.
TONE_OF = {THEMES["default"][tone].lower(): tone for tone in TONES}
# A muted tone in them reads back as its tone, faded.
MUTED_OF = {shade(tone, THEMES["default"]).lower(): tone for tone in TONES}
# A title's leading ticket key, bracketed or not, and its words: a theme can set the words apart while the key keeps the title's colour.
KEY = re.compile(r"(\[?[A-Z][A-Z0-9]*-\d+\]?(?= )|)(.*)", re.S)
# A link's url as the tui opens it: the quoted literal read back, so repr's escapes never reach the href.
LINK = re.compile(r"@click=app\.open_link\(('.*?'|\".*?\")\)")
# Each box's colour, in turn: its LCARS bracket and its sidebar button share it.
COLORS = ("accent", "line", "blue", "warn", "bad", "ok")
# Every pr and ticket opens in a tab of its own, so the board stays put.
NEW_TAB = 'target="_blank" rel="noopener"'
PAGE = Template(Path(__file__).with_name("web.html").read_text(encoding="utf-8"))
CSS = Path(__file__).with_name("web.css").read_text(encoding="utf-8")


def page(board, settings, snoozed, at, boxes, numbers, every):
    """boxes are the page's sections, by key: their name, what an empty one says and its cell widths, and numbers the page's own numbering;
    snoozed hides what the TUI hides."""
    # Built in the default theme so the TUI's theme never reaches the page.
    with theme.using("default"):
        found = entries(board, settings)
    for key, items in snoozed.items():
        found[key] = awake(found[key], items, board["changes"])
    level = condition(board["prs"], settings.github_user)
    when = dt.datetime.fromtimestamp(at)
    # The page dates its refresh: a page left open shows its age.
    status = {name: frames.status(name, when, settings.github_user, "%b %d %H:%M") for name in THEMES}
    return PAGE.substitute(every=every, at=f"{at * 1000:.0f}", tailwind=TAILWIND, tailwind_hash=TAILWIND_HASH, css=CSS, faces=faces(),
                           palettes="\n".join(palette(name, colors) for name, colors in THEMES.items()),
                           colors="\n".join(f"  --color-{name}: var(--{name});" for name in THEMES["default"]),
                           level=level, tone=LEVELS[level], condition=worded({name: frames.condition_label(name, level) for name in THEMES}),
                           status=worded(status), shows="\n".join(f"[data-theme={name}] [data-show~={name}] {{ display: revert; }}" for name in THEMES),
                           options="\n".join(f'<option value="{name}">{name}</option>' for name in THEMES),
                           frames=json.dumps({name: FRAMES.get(name, "") for name in THEMES}),
                           buttons="\n".join(button(key, name, numbers[key], COLORS[n % len(COLORS)], len(found[key]))
                                              for n, (key, (name, _, _)) in enumerate(boxes.items())),
                           sections="\n".join(section(key, name, empty, widths, numbers[key], COLORS[n % len(COLORS)], found[key])
                                               for n, (key, (name, empty, widths)) in enumerate(boxes.items())),
                           details=frame("details", named("details", "details"), "", "", COLORS[0], "minmax(0,1fr)",
                                         '<div id="detail" class="whitespace-pre-wrap px-2"><span class="text-dim">click a row to read its details</span></div>'),
                           **pieces(board, level, every))







def button(key, name, number, color, count):
    return (f'<a href="#{key}" class="button" style="--c: var(--{color})"><span class="count">{count}</span>'
            f'<span>{number:02d} {named(key, name)}</span></a>')




def palette(name, colors):
    selector = ":root" if name == "default" else f':root[data-theme="{name}"]'
    return f"{selector} {{ {' '.join(f'--{key}: {value};' for key, value in colors.items())} }}"


def section(key, name, empty, widths, number, color, items):
    lines, group = [], None
    for entry in items:
        if entry.group and entry.group != group:
            group = entry.group
            size = sum(1 for other in items if other.group == group)
            lines.append(f'<div class="col-span-full mt-2 px-2 font-bold">── {esc(group)} ({size}) ──</div>')
        lines.append(row(f"{key} {entry.url} {entry.search}", entry, widths))
    body = "\n".join(lines) or f'<div class="col-span-full px-2 text-dim">{esc(empty)}</div>'
    # The cell the TUI gives the room the others leave takes it here too; the others take their widest row, so columns line up.
    columns = "_".join("minmax(0,1fr)" if width is None else "auto" for width in widths)
    return frame(key, named(key, name), len(items), f"{number:02d}", color, columns, body)


def frame(key, name, count, number, color, columns, body):
    return (f'<section id="{key}" class="box rounded border border-line bg-raised p-2" style="--c: var(--{color})">\n'
            f'<h2 class="box-head mb-1 px-2 font-bold text-accent"><span class="box-number">{number}</span><span class="box-name">{name}</span>'
            f'<span class="box-jp">{JAPANESE[key]}</span> '
            f'<span class="box-count text-dim">{count}</span><span class="box-cap"></span></h2>\n'
            f'<div class="box-side" aria-hidden="true"><span></span><span></span><span></span></div>\n'
            f'<div class="box-body grid grid-cols-[{columns}] content-start gap-x-3">\n{body}\n</div>\n</section>')


def row(detail, entry, widths):
    cells = "".join(cell(value, tone, width, entry.progress) for (value, tone), width in zip(entry.cells, widths))
    detail = esc(detail)
    link = f'href="{esc(entry.url)}" {NEW_TAB} ' if entry.url else ""
    return (f'<a {link}data-detail="{detail}" class="col-span-full grid grid-cols-subgrid items-center rounded px-2 py-0.5 '
            f'hover:bg-pick aria-[current=true]:bg-pick-focus">{cells}</a>'
            f'<template data-detail="{detail}">{detail_html(folded(entry.detail, entry.fold, DESCRIPTION_LINES))}</template>')


def detail_html(markup):
    """The TUI's details markup as html: its colours as tones, bold as bold, and its links to the web as links."""
    content = Content.from_markup(markup)
    cuts = sorted({0, len(content.plain), *(n for span in content.spans for n in (span.start, span.end))})
    # The TUI's key hints are spans of their own: the page drops them whole and keeps any text that only reads like one.
    return "".join(piece(content, start, end) for start, end in zip(cuts, cuts[1:]) if content.plain[start:end] not in KEY_HINTS)


def piece(content, start, end):
    style = " ".join(str(span.style) for span in content.spans if span.start <= start and end <= span.end)
    words = style.lower().split()
    classes = ([f"text-{TONE_OF[word]}" for word in words if word in TONE_OF] + [f"text-{MUTED_OF[word]} opacity-65" for word in words if word in MUTED_OF]
               + ["font-bold"] * bool({"b", "bold"} & set(words)))
    text = esc(content.plain[start:end])
    text = f'<span class="{" ".join(classes)}">{text}</span>' if classes else text
    link = LINK.search(style)
    url = ast.literal_eval(link.group(1)) if link else ""
    return f'<a href="{esc(url)}" {NEW_TAB} class="underline">{text}</a>' if url.startswith(("https://", "http://")) else text


def cell(value, tone, width, progress):
    if isinstance(value, Text) and progress:
        done, total = progress
        percent = round(100 * done / total) if total else 0
        return f'<span class="h-2 w-40 rounded bg-line"><span class="block h-2 rounded bg-ok" style="width:{percent}%"></span></span>'
    color, _, kind = tone.partition("-")
    room = "min-w-0 truncate" if width is None else "whitespace-nowrap" + (" text-right" if kind == "right" else "")
    text = value.plain if isinstance(value, Text) else value
    look = " ".join(filter(None, [f"text-{color}" if color in TONES else "", KINDS.get(kind, "")]))
    tone = f' style="--t: var(--{color})"' if kind == "pill" and color in TONES else ""
    return f'<span class="{room}"><span class="{look}"{tone}>{title(text) if width is None else esc(text)}</span></span>'


def title(text):
    key, words = KEY.fullmatch(text).groups()
    return f'{esc(key)}<span class="words">{esc(words)}</span>'
