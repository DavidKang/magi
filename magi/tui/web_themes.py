"""Each theme's own pieces of the web page: its typefaces, the LCARS frame and its eggs, NERV's vote, EVA 01's battery, Cyberpunk's heat
and the title cards, as html the page shows only while their theme is picked."""

import base64
import html
import re
from functools import cache
from pathlib import Path

from . import frames
from .theme import THEMES

LEVELS = ("green", "yellow", "red")
# The page carries its typefaces, so no font host sees the board. All are under the OFL. Each face: its family, file and weights.
FACES = (
    # Antonio, thelcars.com's, from @fontsource-variable/antonio 5.3.0 (fonts/OFL.txt).
    ("Antonio", "antonio.woff2", "100 700"),
    # Rajdhani, Cyberpunk 2077's, from @fontsource/rajdhani 5.2.5 (fonts/RAJDHANI-LICENSE.txt).
    ("Rajdhani", "rajdhani-500.woff2", "500"),
    ("Rajdhani", "rajdhani-700.woff2", "700"),
    # Hubot Sans and Monaspace Neon, GitHub's own, for the default theme, from @fontsource/hubot-sans and @fontsource/monaspace-neon 5.2.5
    # (fonts/HUBOT-SANS-LICENSE.txt, fonts/MONASPACE-LICENSE.txt).
    ("Hubot Sans", "hubot-sans-700.woff2", "700"),
    ("Monaspace Neon", "monaspace-neon-400.woff2", "400"),
    ("Monaspace Neon", "monaspace-neon-700.woff2", "700"),
    # DSEG7, Unit-01's battery clock, from the dseg npm package 0.46.0 (fonts/DSEG-LICENSE.txt).
    ("DSEG7", "dseg7.woff2", None),
)
# The panel code on the LCARS elbow: the TUI's for okuda, Picard's Enterprise for picard.
CODES = {"okuda": frames.PANEL_CODE, "picard": "NCC-1701-D"}
# thelcars.com splits its bars into blocks of colour, each block's colour and share of the bar; the first runs on from its elbow.
BARS = (("elbow", 3), ("accent", 1), ("blue", 6), ("warn", 2))
LOWER_BARS = (("elbow", 5), ("warn", 2), ("blue", 6), ("accent", 1))
# Star Trek's running in-joke number: it ends the LCARS sidebar and hides in the data cascade, with the Enterprise's 1701.
FORTY_SEVEN = "47"
CASCADE_ROWS, CASCADE_COLUMNS = 3, 14
EGGS = {9: FORTY_SEVEN, 26: "1701"}
# NERV puts the board to the MAGI: each one's vote by alert level, Casper the first to dissent.
MAGI = ("MELCHIOR-1", "BALTHASAR-2", "CASPER-3")
VOTES = {"green": ("承認", "承認", "承認"), "yellow": ("承認", "承認", "否決"), "red": ("否決", "否決", "否決")}
# NERV's screens are bilingual: each box's name in Japanese beside its English one.
JAPANESE = {"kanban": "看板", "prs": "出撃", "changes": "作戦記録", "epics": "計画", "mine_prs": "個人出撃", "mine_tickets": "個人命令",
            "details": "MAGI解析"}
# The title card a theme opens on. NERV's: its motto while the board holds, the first Angel's episode at pattern blue.
# EVA 01's: Shinji's line as he climbs into Unit-01. Cyberpunk's: Johnny Silverhand's, from the game's 2019 trailer.
# Each card's last line is its small one.
MOTTO = ("神は天にいまし", "全て世は事もなし", "GOD'S IN HIS HEAVEN. ALL'S RIGHT WITH THE WORLD.")
RUN = ("逃げちゃダメだ", "逃げちゃダメだ", "逃げちゃダメだ", "I MUSTN'T RUN AWAY.")
CARDS = {"nerv": {"green": MOTTO, "yellow": MOTTO, "red": ("使徒、襲来", "EPISODE:1 ANGEL ATTACK")}, "eva01": dict.fromkeys(LEVELS, RUN),
         "cyberpunk": dict.fromkeys(LEVELS, ("WAKE UP, SAMURAI.", "WE HAVE A CITY TO BURN."))}
# Night City's wanted level runs to five stars; the alert label says how many are lit.
STARS = 5
# Unit-01's sync ratio: Shinji's first test, and the 400% it reached when it went berserk.
SYNC = {"green": "41.3%", "yellow": "41.3%", "red": "400%"}


def esc(value):
    return html.escape(str(value))


@cache
def faces():
    """The page's @font-face rules, each typeface inlined; read once, on the first page, not when the TUI starts."""
    return "\n".join(face(family, name, weight) for family, name, weight in FACES)


def face(family, name, weight):
    data = base64.b64encode(Path(__file__).with_name("fonts").joinpath(name).read_bytes()).decode()
    weighted = f" font-weight: {weight};" if weight else ""
    return f'@font-face {{ font-family: "{family}"; src: url(data:font/woff2;base64,{data}) format("woff2");{weighted} }}'


def pieces(board, level, every):
    """Each theme's pieces for a board at its alert level, by the page's placeholder."""
    return {"code": worded(CODES), "egg": FORTY_SEVEN, "columns": CASCADE_COLUMNS, "cascade": cascade(board), "bars": bars(BARS),
            "lower": bars(LOWER_BARS), "magi": magi(level), "card": "".join(card(name, cards[level]) for name, cards in CARDS.items()),
            "sync": SYNC[level], "clock": f"{every // 60}:{every % 60:02}:00", "heat": heat(frames.condition_label("cyberpunk", level))}


def worded(words):
    """Each theme's words, by theme, as spans the page shows only while their theme is picked."""
    themes = {}
    for name, text in words.items():
        themes.setdefault(text, []).append(name)
    return "".join(f'<span data-show="{" ".join(names)}">{esc(text)}</span>' for text, names in themes.items())


def named(key, default):
    return worded({name: frames.box_name(name, key, default) for name in THEMES})


def card(name, lines):
    *large, small = lines
    return "".join(f'<p data-show="{name}">{esc(line)}</p>' for line in large) + f'<p data-show="{name}" class="sub">{esc(small)}</p>'


def heat(label):
    lit = label.count("★")
    stars = "".join(f'<span class="star{" on" if n < lit else ""}">★</span>' for n in range(STARS))
    return f'<div class="heat" role="img" aria-label="{esc(label)}">{stars}</div>'


def cascade(board):
    """The LCARS data cascade: the board's pr and ticket numbers, over and over, with the eggs hidden among them."""
    numbers = [re.sub(r"\D", "", pr.url.rsplit("/", 1)[-1]) for pr in board["prs"] + board["my_prs"]]
    numbers += [re.sub(r"\D", "", ticket.key) for ticket in board["my_tickets"]]
    numbers = [number for number in numbers if number] or ["0"]
    cells = [EGGS.get(n, numbers[n % len(numbers)]) for n in range(CASCADE_ROWS * CASCADE_COLUMNS)]
    return "".join(f'<span style="--n: {n % CASCADE_COLUMNS}">{esc(cell)}</span>' for n, cell in enumerate(cells))


def bars(blocks):
    return "".join(f'<span style="--c: var(--{color}); --w: {share}"></span>' for color, share in blocks)


def magi(level):
    votes = VOTES[level]
    passed = "可決" if votes.count("承認") > len(votes) / 2 else "否決"
    return "".join(f'<span class="vote" data-vote="{vote}"><b>{name}</b><i>{vote}</i></span>' for name, vote in zip(MAGI, votes)) + \
        f'<span class="decision">決議 <b>{passed}</b></span>'
