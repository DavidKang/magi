import base64
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from builders import PR_ONE, ROOT, STATED, board
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


@pytest.mark.usefixtures("settings")
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



@pytest.mark.usefixtures("settings")
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
