"""The board as a web page the TUI writes after each refresh: built from the cache only, in a theme the page picks for itself."""

import datetime as dt
import html
import json
import re
from string import Template

from rich.text import Text
from textual.content import Content

from ..domain.review import condition
from ..domain.snoozes import awake
from . import frames, theme
from .entries import KEY_HINTS, entries
from .theme import LCARS, THEMES

# Tailwind's browser build: Magi has no node toolchain to compile the css ahead. The hash pins the file, so a changed one never runs.
TAILWIND = "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.1.4/dist/index.global.js"
TAILWIND_HASH = "sha384-ire6tt7Y6e2HMB3Q+cZpObkqM8M2DVZO9LimwpwuDZstD6FxU2vhSkUzEBlAX3dh"
TONES = ("ok", "bad", "warn", "blue", "dim", "accent")
# A cell's kind after its tone, as the TUI names it: dim-right, warn-pill, bad-alarm.
KINDS = {"pill": "rounded-full border px-2 text-xs uppercase", "alarm": "font-bold uppercase"}
LEVELS = {"green": "ok", "yellow": "warn", "red": "bad"}
# The details are built in the default theme, so each colour in them reads back as the tone it came from.
TONE_OF = {THEMES["default"][tone].lower(): tone for tone in TONES}
LINK = re.compile(r"@click=app\.open_link\((['\"])(.*?)\1\)")
# An LCARS theme frames each box as a panel after thelcars.com: an elbow in one of these colours, in turn, with the box's number.
ELBOWS = ("accent", "line", "blue", "warn", "bad", "ok")
PAGE = Template("""<!doctype html>
<html lang="en" data-theme="default">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="$every">
<title>Magi</title>
<script src="$tailwind" integrity="$tailwind_hash" crossorigin="anonymous"></script>
<style>
$palettes
[data-show] { display: none; }
$shows
</style>
<style type="text/tailwindcss">
@theme {
$colors
  --font-lcars: "Antonio", "Avenir Next Condensed", "Arial Narrow", sans-serif;
}
@custom-variant lcars (&:where($lcars));
</style>
</head>
<body class="min-h-screen bg-bg font-mono text-sm text-fg">
<header class="flex flex-wrap items-center gap-4 border-b border-line bg-raised px-4 py-3">
<h1 class="text-lg font-bold text-accent">magi</h1>
<span class="rounded-full bg-$level px-3 font-bold text-bg">$condition</span>
<span class="text-dim">$status</span>
<select id="theme" class="ml-auto rounded border border-line bg-bg px-2 py-1 text-fg">
$options
</select>
</header>
<main class="grid gap-4 p-4 xl:grid-cols-[minmax(0,1fr)_32rem]">
<div class="grid content-start gap-4 lg:grid-cols-2">
$sections
</div>
<aside class="self-start xl:sticky xl:top-4">
$details
</aside>
</main>
<script>
const THEMES = $names;
const pick = document.getElementById("theme");
const use = (name) => { document.documentElement.dataset.theme = name; pick.value = name; };
try { const saved = localStorage.getItem("magi-theme"); if (THEMES.includes(saved)) use(saved); } catch (e) {}
pick.addEventListener("change", () => { use(pick.value); try { localStorage.setItem("magi-theme", pick.value); } catch (e) {} });
const rows = [...document.querySelectorAll("a[data-detail]")];
const show = (row) => {
  rows.forEach((other) => other.removeAttribute("aria-current"));
  row.setAttribute("aria-current", "true");
  document.getElementById("detail").innerHTML = row.nextElementSibling.innerHTML;
  try { sessionStorage.setItem("magi-detail", row.dataset.detail); } catch (e) {}
};
// A plain click reads the row's details; cmd or ctrl click still opens it on github or jira.
rows.forEach((row) => row.addEventListener("click", (event) => {
  if (event.metaKey || event.ctrlKey || event.shiftKey) return;
  event.preventDefault();
  show(row);
}));
// The page reloads itself after each refresh: the row read before stays open.
try { const kept = rows.find((row) => row.dataset.detail === sessionStorage.getItem("magi-detail")); if (kept) show(kept); } catch (e) {}
</script>
</body>
</html>
""")


def esc(value):
    return html.escape(str(value))


def page(board, settings, snoozed, at, boxes, numbers, every):
    """boxes are the TUI's sections, by key: their name, what an empty one says and its cell widths, and numbers what the TUI numbers them;
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
    return PAGE.substitute(every=every, tailwind=TAILWIND, tailwind_hash=TAILWIND_HASH, palettes="\n".join(palette(name, colors) for name, colors in THEMES.items()),
                           colors="\n".join(f"  --color-{name}: var(--{name});" for name in THEMES["default"]),
                           level=LEVELS[level], condition=worded({name: frames.condition_label(name, level) for name in THEMES}), status=worded(status),
                           shows="\n".join(f"[data-theme={name}] [data-show~={name}] {{ display: revert; }}" for name in THEMES),
                           options="\n".join(f'<option value="{name}">{name}</option>' for name in THEMES),
                           names=json.dumps(list(THEMES)), lcars=", ".join(f"[data-theme={name}] *" for name in LCARS),
                           sections="\n".join(section(key, name, empty, widths, numbers[key], ELBOWS[n % len(ELBOWS)], found[key])
                                               for n, (key, (name, empty, widths)) in enumerate(boxes.items())),
                           details=frame("details", named("details", "details"), "", "", ELBOWS[0], "minmax(0,1fr)",
                                         '<div id="detail" class="whitespace-pre-wrap px-2"><span class="text-dim">click a row to read its details</span></div>'))


def worded(words):
    """Each theme's words, by theme, as spans the page shows only while their theme is picked."""
    themes = {}
    for name, text in words.items():
        themes.setdefault(text, []).append(name)
    return "".join(f'<span data-show="{" ".join(names)}">{esc(text)}</span>' for text, names in themes.items())


def named(key, default):
    return worded({name: frames.box_name(name, key, default) for name in THEMES})


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
        # The same item can sit in a box twice, as two attention reasons on one pr: what the row searches by tells them apart.
        lines.append(row(f"{key} {entry.url} {entry.search}", entry, widths))
    body = "\n".join(lines) or f'<div class="col-span-full px-2 text-dim">{esc(empty)}</div>'
    # The cell the TUI gives the room the others leave takes it here too; the others take their widest row, so columns line up.
    columns = "_".join("minmax(0,1fr)" if width is None else "auto" for width in widths)
    return frame(key, named(key, name), len(items), f"{number:02d}", color, columns, body)


def frame(key, name, count, number, color, columns, body):
    return (f'<section id="{key}" class="rounded border border-line bg-raised p-2 lcars:grid lcars:grid-cols-[5rem_1fr] lcars:grid-rows-[auto_1fr] lcars:rounded-none '
            f'lcars:border-0 lcars:bg-transparent lcars:p-0">\n'
            f'<div class="hidden lcars:block row-span-2 rounded-l-[2rem] bg-{color} px-2 pt-8 text-right font-lcars text-xl font-bold text-bg">'
            f'{number}</div>\n'
            f'<h2 class="mb-1 px-2 font-bold text-accent lcars:mb-0 lcars:flex lcars:h-6 lcars:items-center lcars:gap-2 lcars:px-0">'
            f'<span class="hidden lcars:block h-6 flex-1 bg-{color}"></span>'
            f'<span class="lcars:font-lcars lcars:text-xl lcars:uppercase lcars:text-{color}">{name}</span> '
            f'<span class="text-dim lcars:font-lcars lcars:text-xl">{count}</span>'
            f'<span class="hidden lcars:block h-6 w-6 rounded-r-full bg-{color}"></span></h2>\n'
            f'<div class="relative grid grid-cols-[{columns}] content-start gap-x-3 lcars:pb-2 lcars:pl-6 lcars:pt-4">\n'
            # The inner curve where the elbow's bar meets its side.
            f'<span class="absolute left-0 top-0 hidden h-6 w-6 bg-{color} lcars:block"><span class="block h-6 w-6 rounded-tl-[1.5rem] bg-bg"></span></span>\n'
            f'{body}\n</div>\n</section>')


def row(detail, entry, widths):
    cells = "".join(cell(value, tone, width, entry.progress) for (value, tone), width in zip(entry.cells, widths))
    detail = esc(detail)
    return (f'<a href="{esc(entry.url)}" data-detail="{detail}" class="col-span-full grid grid-cols-subgrid items-center rounded px-2 py-0.5 '
            f'hover:bg-pick aria-[current=true]:bg-pick-focus">{cells}</a>'
            f'<template data-detail="{detail}">{detail_html(entry.detail)}</template>')


def detail_html(markup):
    """The TUI's details markup as html: its colours as tones, bold as bold, and its links to the web as links."""
    content = Content.from_markup(markup)
    cuts = sorted({0, len(content.plain), *(n for span in content.spans for n in (span.start, span.end))})
    # The TUI's key hints are spans of their own: the page drops them whole and keeps any text that only reads like one.
    return "".join(piece(content, start, end) for start, end in zip(cuts, cuts[1:]) if content.plain[start:end] not in KEY_HINTS)


def piece(content, start, end):
    style = " ".join(str(span.style) for span in content.spans if span.start <= start and end <= span.end)
    words = style.lower().split()
    classes = [f"text-{TONE_OF[word]}" for word in words if word in TONE_OF] + ["font-bold"] * bool({"b", "bold"} & set(words))
    text = esc(content.plain[start:end])
    text = f'<span class="{" ".join(classes)}">{text}</span>' if classes else text
    link = LINK.search(style)
    return f'<a href="{esc(link.group(2))}" class="underline">{text}</a>' if link and link.group(2).startswith(("https://", "http://")) else text


def cell(value, tone, width, progress):
    if isinstance(value, Text) and progress:
        done, total = progress
        percent = round(100 * done / total) if total else 0
        return f'<span class="h-2 w-40 rounded bg-line"><span class="block h-2 rounded bg-ok" style="width:{percent}%"></span></span>'
    color, _, kind = tone.partition("-")
    room = "min-w-0 truncate" if width is None else "whitespace-nowrap" + (" text-right" if kind == "right" else "")
    text = value.plain if isinstance(value, Text) else value
    look = " ".join(filter(None, [f"text-{color}" if color in TONES else "", KINDS.get(kind, "")]))
    return f'<span class="{room}"><span class="{look}">{esc(text)}</span></span>'
