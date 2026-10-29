import asyncio
import html
import json
import re
import tomllib
from pathlib import Path

import pytest

from builders import EPIC, PR_ONE, PR_TWO, STATED, bare_board, board, magi_app, make_pr, make_ticket, make_ticket_detail, started
from magi.adapters import storage
from magi.domain.review import condition
from magi.tui import entries, frames, web
from magi.tui.board_files import REFRESH_SECONDS
from magi.tui.boxes import NUMBERS, SECTIONS
from magi.tui.theme import FRAMES, LCARS, THEMES


def two_prs():
    return board([PR_ONE, PR_TWO])


def page(cache):
    return cache.with_name("board.html").read_text()


def box(found, key):
    return re.search(rf'<section id="{key}".*?</section>', found, re.S).group()


def render(found):
    return web.page(found, STATED, {"prs": {}}, 1000.0, SECTIONS, NUMBERS, REFRESH_SECONDS)


async def write_after_a_refresh(cache):
    async with started(magi_app(cache, load=two_prs)):
        pass
    found = page(cache)
    assert f'href="{PR_TWO.url}"' in box(found, "prs") and html.escape(PR_TWO.title) in box(found, "prs"), \
        "a refresh writes the board as a web page next to the cache, each team pr linking to github"
    assert 'http-equiv="refresh"' not in found and f'data-at="{1000.0 * 1000:.0f}"' in found and "location.reload()" in found, \
        "the page reloads after the tui's next refresh, timed from the refresh it shows rather than from when it was opened"
    assert all(f'<option value="{name}">' in found for name in THEMES), "the page offers every theme in its own picker"
    assert 'style="width:50%"' in box(found, "epics"), "an epic's bar fills with its done tickets"
    assert "updated Jan 01 01:16" in found, "the page names the day and time of the refresh it shows, so a stale page shows its age"
    assert re.search(r'<script src="[^"]+" integrity="sha384-[^"]+" crossorigin="anonymous"></script>', found), \
        "the browser runs the cdn's tailwind only when it matches the pinned file's hash"


@pytest.mark.usefixtures("default_theme")
def test_a_refresh_writes_the_web_page(cache):
    asyncio.run(write_after_a_refresh(cache))


async def keep_the_board_when_the_page_fails(cache, monkeypatch):
    write_text = storage.write_text

    def full(path, text):
        if path.name == "board.html":
            raise OSError("No space left on device")
        write_text(path, text)
    monkeypatch.setattr(storage, "write_text", full)
    async with started(magi_app(cache, load=two_prs)) as pilot:
        assert pilot.app.focused is not None, "the board takes the focus as usual"
        assert any("web page" in n.message and "No space left on device" in n.message for n in pilot.app._notifications), \
            "a page that cannot be written is told, and the board carries on: the page is only an extra view of it"


@pytest.mark.usefixtures("default_theme")
def test_a_page_that_cannot_be_written_never_takes_the_board_down(cache, monkeypatch):
    asyncio.run(keep_the_board_when_the_page_fails(cache, monkeypatch))


def test_pr_and_ticket_links_open_in_a_new_tab():
    found = render(two_prs())
    links = re.findall(r'<a href="https?://[^"]*"[^>]*>', found)
    assert links and all('target="_blank" rel="noopener"' in link for link in links), \
        f"every pr and ticket link, in the boxes and in the details, opens in a tab of its own: {[l for l in links if 'target' not in l][:3]}"


def test_a_change_without_a_link_points_nowhere():
    change = {"at": "2026-10-24T02:04", "tone": "commented", "label": "Moved", "note": None, "aside": None, "told": False, "item": None, "group": None,
              "subject": {"kind": "ticket", "url": None, "ref": "ACME-1", "title": "ACME-1 Gone"}}
    found = box(render(bare_board(changes=[change])), "changes")
    assert "ACME-1 Gone" in found and 'href="None"' not in found, "a change with nothing to open is still read, but links nowhere"

def test_a_blocked_kanban_ticket_shows_its_red_pill_on_the_page():
    blocked = make_ticket(key="ACME-1", status="En proceso", detail=make_ticket_detail(labels=["blocked"]))
    found = box(render(bare_board(kanban=[blocked])), "kanban")
    assert re.search(r'<span class="text-bad pill[^"]*" style="--t: var\(--bad\)">blocked</span>', found), \
        "a kanban ticket labelled blocked shows a red blocked pill on the page as in the tui"


async def snooze_on_the_page(cache):
    async with started(magi_app(cache, load=two_prs)) as pilot:
        assert PR_ONE.url in box(page(cache), "prs"), "the team pr is on the page before the snooze"
        await pilot.press("4", "s")
        await pilot.pause()
    assert PR_ONE.url not in box(page(cache), "prs"), "a snoozed item leaves the web page as it leaves the tui"


@pytest.mark.usefixtures("default_theme")
def test_a_snoozed_item_leaves_the_web_page(cache):
    asyncio.run(snooze_on_the_page(cache))


async def written_in(cache, name):
    cache.parent.mkdir(exist_ok=True)
    async with started(magi_app(cache, load=two_prs, theme=name)):
        pass
    return page(cache)


@pytest.mark.usefixtures("default_theme")
def test_the_web_page_ignores_the_tui_theme(tmp_path):
    pages = {name: asyncio.run(written_in(tmp_path / name / "cache.json", name)) for name in THEMES}
    assert len(set(pages.values())) == 1, "the web page picks its own theme: the tui's theme does not change it"


def test_the_web_page_escapes_what_github_and_jira_send():
    hostile = make_pr(title='<script>alert(1)</script> "quoted"', author={"login": '<b onclick="x">eve</b>'})
    found = render(bare_board(prs=[hostile], my_tickets=[make_ticket(status="<i>Blocked</i>")]))
    assert "<script>" not in box(found, "prs") and "<b " not in box(found, "prs"), "pr titles and authors never reach the page as markup"
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &quot;quoted&quot;" in box(found, "prs"), "pr titles show as the text they are"
    assert "<i>" not in box(found, "mine_tickets") and "── &lt;i&gt;Blocked&lt;/i&gt; (1) ──" in box(found, "mine_tickets"), \
        "a jira status heading its group shows as the text it is"


def test_the_web_page_draws_empty_boxes_ticketless_epics_and_groups():
    found = render(bare_board(epics=[EPIC], tickets_by_epic={EPIC.key: []}, prs=[PR_ONE, PR_TWO]))
    assert "no open prs" in box(found, "mine_prs"), "an empty box says so, as in the tui"
    assert 'style="width:0%"' in box(found, "epics"), "an epic without tickets draws an empty bar"
    assert re.search(r"── [a-z ]+ \(1\) ──", box(found, "prs")), "team prs sit under their turn's heading, with its count"
    assert "grid-cols-[minmax(0,1fr)_auto_auto_auto_auto]" in box(found, "prs") and "grid-cols-subgrid" in box(found, "prs"), \
        "rows share their box's columns, so each column lines up and the title takes the room the others leave, as in the tui"


def test_the_page_turns_each_themes_frame_on_with_it():
    found = render(bare_board())
    script = json.loads(re.search(r"const FRAMES = (.*);", found).group(1))
    assert script == {name: FRAMES.get(name, "") for name in THEMES}, "picking a theme turns on the frame the tui draws for it, and only that one"
    assert "[data-frame=lcars]" in found and "prefers-reduced-motion" in found, \
        "the lcars frame has its own look, and its motion stops for whoever asks the browser for less"
    assert re.search(r'font-family: "Antonio"; src: url\(data:font/woff2;base64,[A-Za-z0-9+/=]+\)', found), \
        "lcars sets its words in Antonio, thelcars.com's typeface, carried in the page"
    assert "fonts.googleapis" not in found, "the page asks no font host for anything, so none can read the board through its css"


def test_the_package_carries_the_files_the_web_page_reads():
    data = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]["magi.tui"]
    assert {"web.html", "web.css", "fonts/antonio.woff2", "fonts/OFL.txt", "fonts/dseg7.woff2", "fonts/DSEG-LICENSE.txt",
            "fonts/rajdhani-500.woff2", "fonts/rajdhani-700.woff2", "fonts/RAJDHANI-LICENSE.txt",
            "fonts/hubot-sans-700.woff2", "fonts/HUBOT-SANS-LICENSE.txt",
            "fonts/monaspace-neon-400.woff2", "fonts/monaspace-neon-700.woff2", "fonts/MONASPACE-LICENSE.txt"} <= set(data), \
        "an installed magi carries the web page's template, its css and its typeface with the typeface's licence"


def test_lcars_frames_the_page_with_a_sidebar_of_numbered_boxes():
    found = render(bare_board())
    sidebar = re.search(r'<nav class="sidebar".*?</nav>', found, re.S).group()
    for key in SECTIONS:
        button = re.search(rf'<a href="#{key}" class="button"[^>]*>(.*?)</a>', sidebar, re.S)
        assert button and f"{NUMBERS[key]:02d}" in button.group(1), "each box has a numbered button in the lcars sidebar, as the tui's side buttons"
        assert frames.box_name("okuda", key, "") in shown(button.group(1), "okuda"), "a sidebar button names its box in lcars words"
    assert re.search(r'<div class="egg">47</div>\s*</nav>', sidebar), "the sidebar ends on 47, star trek's running number, at its very bottom"
    assert frames.PANEL_CODE in shown(found, "okuda") and "NCC-1701-D" in shown(found, "picard"), \
        "the elbow carries its panel code: the tui's for okuda, picard's enterprise for picard"


def test_lcars_cascade_runs_the_boards_numbers():
    found = render(bare_board(prs=[make_pr(url="https://github.com/acme/app/pull/8231")], my_tickets=[make_ticket(key="ACME-5524")]))
    cascade = re.findall(r"<span[^>]*>(\d+)</span>", re.search(r'<div class="cascade".*?</div>', found, re.S).group())
    assert {"8231", "5524"} <= set(cascade), "the lcars data cascade runs the board's pr and ticket numbers"
    assert {"47", "1701"} <= set(cascade), "and hides 47 and 1701 among them"


def test_the_page_carries_the_alert_level_for_its_frame():
    calm, busy = condition([], STATED.github_user), condition([PR_ONE, PR_TWO], STATED.github_user)
    assert calm != busy, "the two boards sit at different alert levels"
    assert f'data-level="{calm}"' in render(bare_board()) and f'data-level="{busy}"' in render(board([PR_ONE, PR_TWO])), \
        "the page carries the board's alert level, so a frame can go to red alert"


def test_each_row_carries_its_details_for_the_side_panel():
    found = render(bare_board(prs=[PR_TWO]))
    detail = re.search(rf'<template data-detail="prs {re.escape(PR_TWO.url)} [^"]*">(.*?)</template>', found, re.S)
    assert detail, "each row carries its details, keyed by box and url, for the panel to show on click"
    assert f'<a href="{PR_TWO.url}" target="_blank" rel="noopener" class="underline">' in detail.group(1), "the details' links open github or jira"
    assert '<span class="text-blue">status' in detail.group(1), "the details keep the tui's tones"
    assert found.count('id="details"') == 1 and '<div id="detail"' in found, "the page has one details panel beside the boxes, waiting for a click"


def test_details_only_link_web_addresses():
    found = web.detail_html("[#21cfac underline @click=app.open_link('javascript:alert(1)')]run[/]")
    assert "href" not in found and "run" in found, "a details link that is not http or https shows as plain text"


def test_details_link_the_url_the_tui_opens():
    found = web.detail_html(entries.link("https://ci.example/a\\b", "log"))
    assert 'href="https://ci.example/a\\b"' in found, "a details link on the page opens the url the tui opens, its backslashes kept single"


def test_details_keep_the_tuis_tones_bold_and_links_as_html():
    found = web.detail_html('[b]<b>Fix</b>[/b] [#56d364]ok[/] [#21cfac underline @click=app.open_link("https://x.test/1")]pr[/]')
    assert found == ('<span class="font-bold">&lt;b&gt;Fix&lt;/b&gt;</span> <span class="text-ok">ok</span> '
                     '<a href="https://x.test/1" target="_blank" rel="noopener" class="underline"><span class="text-accent">pr</span></a>'), \
        "details turn bold into bold, colours into their tones and web links into links, and their text into escaped text"


def shown(found, name):
    return {html.unescape(text) for names, text in re.findall(r'<span data-show="([^"]+)">(.*?)</span>', found) if name in names.split()}


def test_each_theme_names_the_boxes_the_alert_and_the_refresh_its_own_way():
    found = render(bare_board())
    level = condition([], STATED.github_user)
    for name in THEMES:
        assert f"[data-theme={name}] [data-show~={name}]" in found, f"the page shows {name}'s words when {name} is picked"
        assert frames.condition_label(name, level) in shown(found, name), f"{name} names the alert level as the tui does"
    for key, (default, _, _) in SECTIONS.items():
        assert shown(box(found, key), "default") == {default}, "the default theme names each box as the tui's default does"
    assert shown(box(found, "prs"), "okuda") == {"crew reports"} and shown(box(found, "details"), "nerv") == {"magi analysis"}, \
        "a framed theme names its boxes and its details panel as its tui frame does"
    line = re.search(r'<span class="status[^"]*">(.*?)</span>\n', found).group(1)
    status = {name: " ".join(shown(line, name)) for name in THEMES}
    assert "STARDATE" in status["okuda"] and "MELCHIOR BALTHASAR CASPER" in status["nerv"] and "NET UPLINK" in status["cyberpunk"], \
        "each theme words the refresh as its tui status line does"
    assert f"PILOT {STATED.github_user.upper()}" in status["eva01"], "eva01 names its pilot, the github user"
    assert all("Jan 01" in status[name] for name in THEMES if name not in LCARS), \
        "every theme dates the refresh, so a page left open shows its age; lcars dates it in stardates"


def test_the_web_details_drop_the_tuis_key_hints():
    long = make_ticket(detail=make_ticket_detail(description="\n".join(["Press c to read it all", *(f"line {n}" for n in range(40))])))
    found = render(bare_board(my_tickets=[long]))
    assert "line 0" in box(found, "mine_tickets") and "comments" in box(found, "mine_tickets"), "the ticket's details and its comments field reach the page"
    assert "Press c to read it all" in box(found, "mine_tickets"), "the page keeps a ticket's own words, even when they read like a key hint"
    assert "c to open" not in found and found.count("c to read it all") == 1, "the page has no c key, so its details never point at one"


def votes(found):
    return re.findall(r'<span class="vote" data-vote="([^"]+)"><b>([A-Z]+-\d)</b>', found)


def test_nerv_puts_the_board_to_the_magi_vote():
    mine = [make_pr(author={"login": STATED.github_user})]
    levels = {"green": [], "yellow": [make_pr(author={"login": "bob"})], "red": mine}
    assert {level: condition(prs, STATED.github_user) for level, prs in levels.items()} == {level: level for level in levels}, \
        "each board sits at its alert level"
    pages = {level: render(bare_board(prs=prs)) for level, prs in levels.items()}
    calm = pages["green"]
    assert [name for _, name in votes(calm)] == ["MELCHIOR-1", "BALTHASAR-2", "CASPER-3"], "the three magi vote, as on nerv's screens"
    cast = {level: dict((name, vote) for vote, name in votes(found)) for level, found in pages.items()}
    assert {level: list(ballot.values()).count("承認") for level, ballot in cast.items()} == {"green": 3, "yellow": 2, "red": 0}, \
        "a calm board passes unanimously, one magi dissents at pattern orange, and all three reject at pattern blue"
    assert [name for name, vote in cast["yellow"].items() if vote == "否決"] == ["CASPER-3"], "casper is the first to dissent"
    assert "決議 <b>可決</b>" in calm and "決議 <b>可決</b>" in pages["yellow"] and "決議 <b>否決</b>" in pages["red"], \
        "the magi's resolution passes while most of them approve"
    assert '<span class="box-jp">看板</span>' in box(calm, "kanban") and '<span class="box-jp">MAGI解析</span>' in box(calm, "details"), \
        "nerv names each box in japanese too, as its screens are bilingual"


def test_nerv_opens_on_a_title_card():
    calm = re.search(r'<div class="card"[^>]*>(.*?)</div>', render(bare_board()), re.S).group(1)
    mine = [make_pr(author={"login": STATED.github_user})]
    assert condition(mine, STATED.github_user) == "red", "my pr failing ci puts the board at pattern blue"
    assert '<p data-show="nerv">神は天にいまし</p><p data-show="nerv">全て世は事もなし</p>' in calm, \
        "picking nerv shows a title card with nerv's motto while the board is calm"
    assert '<p data-show="eva01">逃げちゃダメだ</p>' in calm, "picking eva01 shows shinji's 'i mustn't run away' instead"
    assert '<p data-show="eva01" class="sub">I MUSTN&#x27;T RUN AWAY.</p>' in calm, "each card's last line is marked apart, so it sets in small type"
    assert '<p data-show="cyberpunk">WAKE UP, SAMURAI.</p><p data-show="cyberpunk" class="sub">WE HAVE A CITY TO BURN.</p>' in calm, \
        "picking cyberpunk wakes the samurai, as johnny silverhand does"
    found = render(bare_board(prs=mine))
    red = re.search(r'<div class="card"[^>]*>(.*?)</div>', found, re.S).group(1)
    assert '<p data-show="nerv">使徒、襲来</p>' in red, "and announces the angel at pattern blue"
    assert '<p data-show="eva01">逃げちゃダメだ</p>' in red and '<p data-show="cyberpunk">WAKE UP, SAMURAI.</p>' in red, \
        "while eva01's and cyberpunk's cards stay the same at every level"
    hidden = re.search(r"^(\.elbow.*)\{ display: none; \}$", found, re.M).group(1)
    assert {".box-jp", ".magi", ".card", ".battery", ".heat", ".rail"} <= {name.strip() for name in hidden.split(",")}, \
        "the japanese names, the vote, the title card, eva01's battery, cyberpunk's heat and default's rail stay out of the themes they don't belong to"


def test_eva01_counts_its_internal_battery_down_to_the_next_reload():
    calm = render(bare_board())
    full = f"{REFRESH_SECONDS // 60}:{REFRESH_SECONDS % 60:02}:00"
    assert f'<b id="clock" data-every="{REFRESH_SECONDS}">{full}</b>' in calm, \
        "unit-01's battery starts full at the page's reload interval, the five minutes an eva lasts on its internal power"
    assert re.search(r'font-family: "DSEG7"; src: url\(data:font/woff2;base64,[A-Za-z0-9+/=]+\)', calm), \
        "its digits are seven-segment ones, the font carried in the page"
    assert '<i aria-hidden="true">8:88:88</i>' in calm, "unlit segments ghost behind the digits, as on a seven-segment display"
    levels = {"green": [], "yellow": [make_pr(author={"login": "bob"})], "red": [make_pr(author={"login": STATED.github_user})]}
    sync = {level: re.search(r"INTERNAL<br>SYNC ([0-9.]+%)", render(bare_board(prs=prs))).group(1) for level, prs in levels.items()}
    assert sync == {"green": "41.3%", "yellow": "41.3%", "red": "400%"}, \
        "the sync ratio reads shinji's first test until the red level, and the 400% of berserk there"


def test_cyberpunk_shows_the_board_as_its_wanted_level():
    levels = {"green": [], "yellow": [make_pr(author={"login": "bob"})], "red": [make_pr(author={"login": STATED.github_user})]}
    heat = {level: re.search(r'<div class="heat"[^>]*>(.*?)</div>', render(bare_board(prs=prs)), re.S) for level, prs in levels.items()}
    assert {level: found.group(1).count('class="star on"') for level, found in heat.items()} == {"green": 0, "yellow": 2, "red": 5}, \
        "night city's wanted level lights as many of its five stars as the alert label carries: none, two, all five for maxtac"
    assert all(found.group(1).count('class="star') == 5 for found in heat.values()), "the meter always shows its five stars"
    assert 'role="img" aria-label="HEAT ★★"' in heat["yellow"].group(0), "the meter reads out as its alert label"
    assert re.search(r'font-family: "Rajdhani"; src: url\(data:font/woff2;base64,[A-Za-z0-9+/=]+\)', render(bare_board())), \
        "cyberpunk sets its words in rajdhani, the game's typeface, carried in the page"


def test_the_default_theme_drains_a_rail_until_the_next_reload():
    found = render(bare_board())
    assert f'<div class="rail" aria-hidden="true" style="--every: {REFRESH_SECONDS}s"></div>' in found, \
        "a rail under the header empties over the page's reload interval, so a glance tells how fresh the board is"
    default = re.search(r"^:root\[data-theme=default\] \{(.*?)^\}", found, re.S | re.M).group(1)
    assert re.search(r"\.rail \{[^}]*animation: drain var\(--every\) linear", default), "the default theme drains it at an even pace"
    still = re.search(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", found, re.S).group(1)
    assert ":root[data-theme=default] .rail { display: none; }" in still, "a rail that cannot drain would always read as fresh, so reduced motion hides it"


def luminance(color):
    channels = [int(color[n:n + 2], 16) / 255 for n in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(one, other):
    light, dark = sorted((luminance(one), luminance(other)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_the_default_theme_reads_at_wcag_aa_in_github_s_own_typefaces():
    found = render(bare_board())
    block = re.search(r"^:root\[data-theme=default\] \{(.*?)^\}", found, re.S | re.M).group(1)
    colors = {**THEMES["default"], **dict(re.findall(r"--([a-z]+): (#[0-9a-f]{6});", block))}
    low = {tone: round(contrast(colors[tone], colors["raised"]), 2) for tone in ("fg", "dim", "accent", "blue", "ok", "warn", "bad")}
    assert all(ratio >= 4.5 for ratio in low.values()), f"every text tone reads at wcag aa (4.5:1) on the boxes: {low}"
    for family in ("Hubot Sans", "Monaspace Neon"):
        assert re.search(rf'font-family: "{family}"; src: url\(data:font/woff2;base64,[A-Za-z0-9+/=]+\)', found), \
            f"the default theme sets its words in github's {family}, carried in the page"
    assert re.search(r'body \{[^}]*font-family: "Monaspace Neon"', block), "the rows read in monaspace neon"
    assert all(re.search(rf'{name} \{{[^}}]*font-family: "Hubot Sans"', block) for name in (r"\.title", r"\.box-name")), \
        "the page's and the boxes' names stand in hubot sans"


def test_a_title_keeps_its_ticket_key_apart_from_its_words():
    found = box(render(bare_board(prs=[make_pr(title="[ACME-12] Fix the <b> tag"), make_pr(number=2, title="Bump the gems")])), "prs")
    assert '[ACME-12]<span class="words"> Fix the &lt;b&gt; tag</span>' in found, \
        "a title's words sit apart from its ticket key, so a theme can set them in white while the key keeps the title's colour"
    assert '<span class="words">Bump the gems</span>' in found, "a title without a ticket key is all words"
