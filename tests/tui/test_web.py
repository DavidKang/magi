import asyncio
import html
import re

import pytest

from builders import EPIC, PR_ONE, PR_TWO, STATED, bare_board, board, magi_app, make_pr, make_ticket, make_ticket_detail, started
from magi.domain.review import condition
from magi.tui import frames, web
from magi.tui.app import NUMBERS, REFRESH_SECONDS, SECTIONS
from magi.tui.theme import LCARS, THEMES


def two_prs():
    return board([PR_ONE, PR_TWO])


def page(cache):
    return cache.with_name("board.html").read_text()


def box(found, key):
    return re.search(rf'<section id="{key}".*?</section>', found, re.S).group()


def render(found):
    return web.page(found, STATED, {"attention": {}, "prs": {}}, 1000.0, SECTIONS, NUMBERS, REFRESH_SECONDS)


async def write_after_a_refresh(cache):
    async with started(magi_app(cache, load=two_prs)):
        pass
    found = page(cache)
    assert f'href="{PR_TWO.url}"' in box(found, "prs") and html.escape(PR_TWO.title) in box(found, "prs"), \
        "a refresh writes the board as a web page next to the cache, each team pr linking to github"
    assert f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}">' in found, "the page reloads itself as often as the tui refreshes"
    assert all(f'<option value="{name}">' in found for name in THEMES), "the page offers every theme in its own picker"
    assert 'style="width:50%"' in box(found, "epics"), "an epic's bar fills with its done tickets"
    assert "updated Jan 01 01:16" in found, "the page names the day and time of the refresh it shows, so a stale page shows its age"
    assert re.search(r'<script src="[^"]+" integrity="sha384-[^"]+" crossorigin="anonymous"></script>', found), \
        "the browser runs the cdn's tailwind only when it matches the pinned file's hash"


@pytest.mark.usefixtures("default_theme")
def test_a_refresh_writes_the_web_page(cache):
    asyncio.run(write_after_a_refresh(cache))


async def snooze_on_the_page(cache):
    async with started(magi_app(cache, load=two_prs)) as pilot:
        assert PR_ONE.url in box(page(cache), "attention"), "the attention item is on the page before the snooze"
        await pilot.press("3", "s")
        await pilot.pause()
    assert PR_ONE.url not in box(page(cache), "attention"), "a snoozed item leaves the web page as it leaves the tui"


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


def test_lcars_themes_frame_each_box_as_an_lcars_panel():
    found = render(bare_board())
    lcars = re.search(r"@custom-variant lcars \((.*)\);", found).group(1)
    assert set(re.findall(r"data-theme=(\w+)", lcars)) == set(LCARS), "the lcars look turns on with each lcars theme, and only with those"
    panel = box(found, "prs")
    assert "hidden lcars:block" in panel, "a box carries its lcars elbow, hidden until an lcars theme is picked"
    assert f">{NUMBERS['prs']:02d}<" in panel, "the elbow shows the box's number, as the tui's lcars side buttons do"
    assert "lcars:uppercase" in panel, "an lcars box names itself in capitals"


def test_each_row_carries_its_details_for_the_side_panel():
    found = render(bare_board(prs=[PR_TWO]))
    detail = re.search(rf'<template data-detail="prs {re.escape(PR_TWO.url)} [^"]*">(.*?)</template>', found, re.S)
    assert detail, "each row carries its details, keyed by box and url, for the panel to show on click"
    assert f'<a href="{PR_TWO.url}" class="underline">' in detail.group(1), "the details' links open github or jira"
    assert '<span class="text-dim">status' in detail.group(1), "the details keep the tui's tones"
    assert found.count('id="details"') == 1 and '<div id="detail"' in found, "the page has one details panel beside the boxes, waiting for a click"


def test_details_only_link_web_addresses():
    found = web.detail_html("[#21cfac underline @click=app.open_link('javascript:alert(1)')]run[/]")
    assert "href" not in found and "run" in found, "a details link that is not http or https shows as plain text"


def test_details_keep_the_tuis_tones_bold_and_links_as_html():
    found = web.detail_html('[b]<b>Fix</b>[/b] [#56d364]ok[/] [#21cfac underline @click=app.open_link("https://x.test/1")]pr[/]')
    assert found == ('<span class="font-bold">&lt;b&gt;Fix&lt;/b&gt;</span> <span class="text-ok">ok</span> '
                     '<a href="https://x.test/1" class="underline"><span class="text-accent">pr</span></a>'), \
        "details turn bold into bold, colours into their tones and web links into links, and their text into escaped text"


def test_two_attention_rows_on_one_pr_keep_their_own_details():
    reasons = [{"subject": {"kind": "pr", "url": PR_ONE.url, "ref": "app#1", "title": "First"}, "reason": reason} for reason in ("Stale", "Unassigned")]
    found = render(bare_board(attention=reasons))
    keys = re.findall(r'<a [^>]*data-detail="([^"]+)"', box(found, "attention"))
    assert len(set(keys)) == 2, "each attention row on the same pr has its own details key, so a reload reopens the row read, not its twin"


def test_a_rows_details_key_survives_its_twin_leaving():
    def reason(why):
        return {"subject": {"kind": "pr", "url": PR_ONE.url, "ref": "app#1", "title": "First"}, "reason": why}
    def key(found):
        return [key for key, detail in re.findall(r'<template data-detail="([^"]+)">(.*?)</template>', box(found, "attention"), re.S) if "Unassigned" in detail]
    both, alone = render(bare_board(attention=[reason("Stale"), reason("Unassigned")])), render(bare_board(attention=[reason("Unassigned")]))
    assert key(both) and key(both) == key(alone), "a row keeps its details key when its twin leaves, so a reload never opens the twin's details"


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
    status = {name: " ".join(shown(found, name) - {frames.condition_label(name, level)} - shown(box(found, "details"), name)
                             - {text for key in SECTIONS for text in shown(box(found, key), name)}) for name in THEMES}
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
