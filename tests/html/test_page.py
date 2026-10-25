import base64
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from builders import PR_ONE, ROOT, STATED, board, make_pr
from tarkon import config
from tarkon.domain import status
from tarkon.domain.entities import Ticket
from tarkon.html import page as web


def test_html_mine():
    page = web.mine([], [], [Ticket(key="ACME-1", summary="Ticket one", status="En proceso")], STATED)
    assert "My open tickets" in page, "html lists my open tickets with their status in English"
    assert "In Progress" in page, "html lists my open tickets with their status in English"
    assert "En proceso" not in page, "html lists my open tickets with their status in English"
    assert "in status" not in page, "html lists my open tickets with their status in English"
    row = web.tui_ticket(Ticket(key="ACME-1", summary="Ticket one", status="En proceso"), [], STATED)["row"]
    assert "In Progress" in row, "the html tui mirror shows my ticket's status in English in three columns"
    assert "En proceso" not in row, "the html tui mirror shows my ticket's status in English in three columns"
    assert row.count("<span") == 3, "the html tui mirror shows my ticket's status in English in three columns"


def test_html_unmapped_status_exits_cleanly(monkeypatch):
    monkeypatch.setattr(config, "load", lambda: STATED)
    given = []

    def build(collect, settings):
        given.append(settings)
        raise status.UnmappedStatus("Unmapped Jira status: Blocked")
    monkeypatch.setattr(web, "build", build)
    with pytest.raises(SystemExit, match="Unmapped Jira status: Blocked"):
        web.main(None)
    assert given == [STATED], "the page is built with the settings just loaded"



def test_html_logo():
    with tempfile.TemporaryDirectory() as scratch:
        found = {**board([PR_ONE]), "merged_by_ticket": {}, "now": {"prs": {}}}
        path, web.OUT = web.OUT, Path(scratch) / "board.html"
        try:
            page = web.build(lambda settings: found, STATED)["out"].read_text()
        finally:
            web.OUT = path
    logo = "data:image/png;base64," + base64.b64encode((Path(web.__file__).parent.parent / "logo.png").read_bytes()).decode()
    assert f'<link rel="icon" type="image/png" href="{logo}">' in page, "html favicon is the logo"
    assert page.count(f'src="{logo}"') == 2, "html headers show the logo instead of the rocket"
    assert "rotate(45 16 16)" not in page, "html headers show the logo instead of the rocket"
    black = "data:image/png;base64," + base64.b64encode((Path(web.__file__).parent.parent / "logo-black.png").read_bytes()).decode()
    assert f'<img class="logo logo-lcars" src="{black}" alt="">' in page, "the LCARS masthead has the black logo"
    assert ".logo-lcars { display: none; }" in page, "only the LCARS design shows the black logo"
    assert ':root[data-design="lcars"] .masthead .logo-lcars { display: block;' in page, "only the LCARS design shows the black logo"


def test_html_lcars_design():
    template = Path(web.__file__).with_name("template.html").read_text()
    assert template.count('<button type="button" data-design="lcars"') == 2, "both design switches offer LCARS"
    assert re.search(r'getItem\("tarkon-design"\).*"lcars"', template.splitlines()[4]) is not None, "the page remembers the LCARS design"
    assert ':root[data-design="lcars"] .masthead' in template, "the LCARS design has its own look"


def test_html_without_config():
    with tempfile.TemporaryDirectory() as home:
        result = subprocess.run([sys.executable, "-m", "tarkon", "html"], capture_output=True, text=True,
                                cwd=ROOT, env={**os.environ, "HOME": home})
    assert result.returncode == 1, "html without config asks to configure first"
    assert "Run `python -m tarkon config` first" in result.stderr, "html without config asks to configure first"


def test_html_lcars_masthead_and_log():
    with tempfile.TemporaryDirectory() as scratch:
        found = {**board([PR_ONE]), "merged_by_ticket": {}, "now": {"prs": {}}}
        path, web.OUT = web.OUT, Path(scratch) / "board.html"
        try:
            page = web.build(lambda settings: found, STATED)["out"].read_text()
        finally:
            web.OUT = path
    assert re.search(r'<span class="not-lcars">Updated \d\d/\d\d/\d{4} \d\d:\d\d</span>'
                     r'<span class="lcars-only">STARDATE \d{4}\.\d\d · UPDATED \d\d:\d\d</span>', page), \
        "LCARS dates the last regeneration in stardates; the other designs keep the date"
    assert '<p class="condition condition-red lcars-only">RED ALERT</p>' in page, "LCARS shows the board's alert level"
    assert '<h2><span class="not-lcars">Recent changes</span><span class="lcars-only">Captain\'s Log</span></h2>' in page, \
        "LCARS calls the changes the Captain's Log"
    assert ".lcars-only { display: none; }" in page, "only the LCARS design shows its own words"
    assert ':root[data-design="lcars"] .lcars-only { display: revert; }' in page, "only the LCARS design shows its own words"
    assert ':root[data-design="lcars"] .not-lcars { display: none; }' in page, "only the LCARS design shows its own words"
    assert ':root[data-design="lcars"] .masthead::after { content: "04-1701";' in page, "the LCARS elbow carries a panel code"


@pytest.mark.parametrize("pr, tone, label", [
    (make_pr(review_decision="APPROVED", ci="passing", mergeable="MERGEABLE"), "green", "CONDITION GREEN"),
    (make_pr(ci="running", mergeable="MERGEABLE"), "yellow", "YELLOW ALERT"),
    (make_pr(author={"login": "bob"}), "yellow", "YELLOW ALERT")])
def test_html_condition_tones(pr, tone, label):
    with tempfile.TemporaryDirectory() as scratch:
        found = {**board([pr]), "merged_by_ticket": {}, "now": {"prs": {}}}
        path, web.OUT = web.OUT, Path(scratch) / "board.html"
        try:
            page = web.build(lambda settings: found, STATED)["out"].read_text()
        finally:
            web.OUT = path
    assert f'<p class="condition condition-{tone} lcars-only">{label}</p>' in page, "the alert level carries its tone"
    assert f':root[data-design="lcars"] .condition-{tone} {{ color: var(--' in page, "every tone has its LCARS colour"


def test_html_shows_what_collect_found():
    found = board([PR_ONE])
    found = {**found, "attention": [{**found["attention"][0], "reason": "Flagged by the refresh only."}], "merged_by_ticket": {},
             "now": {"prs": {}}}
    with tempfile.TemporaryDirectory() as scratch:
        path, web.OUT = web.OUT, Path(scratch) / "board.html"
        try:
            page = web.build(lambda settings: found, STATED)["out"].read_text()
        finally:
            web.OUT = path
    assert page.count("Flagged by the refresh only.") == 2, "the page and its tui mirror show the attention the refresh found"


def test_html_jira_links_use_the_configured_site():
    site = config.Settings(team=["alice"], jira_project="ACME", github_user="me", github_org="acme", jira_url="https://acme.atlassian.net/")
    assert 'href="https://acme.atlassian.net/browse/ACME-9"' in web.jira_link("ACME-9", site), "jira links use the configured site"
