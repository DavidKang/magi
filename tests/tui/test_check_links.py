import asyncio
from dataclasses import replace

import pytest
from textual.actions import parse
from textual.markup import to_content
from textual.style import Style

from builders import PR_ONE, PR_TWO, STATED, board, light_node, magi_app, started
from magi.adapters import github
from magi.tui import entries

# Check urls their poster could craft to break the detail's markup, inject an action or reach `open` as something else.
HOSTILE = ["https://ci.example/a]b", "https://ci.example/a[b", "https://ci.example/a[/]b", "https://ci.example/a(b)c",
           "https://ci.example/a\\b", "https://ci.example/a\nb", "https://ci.example/a\rb", "https://ci.example/a\tb",
           "https://ci.example/a b", "https://ci.example/\x00", "https://ci.example/\x1b[31m", "https://ci.example/a`b$c;d|e",
           "https://ci.example/a=b @click=app.quit()", "https://ci.example/a]x[@click=app.quit()]y",
           "https://ci.example/a)[/][@click=app.quit()]x", "https://ci.example/%27%22", "https://ci.example/a{b}c"]
REJECTED = ["file:///etc/hosts", "http://ci.example/a", "javascript:alert(1)", "vscode://file/etc/hosts", "-a", "",
            "https://ci.example/a'b", "https://ci.example/a\"b", "https://ci.example/a'b\"c"]
CHECKS_PAGE = PR_TWO.url + "/checks"


def failed_check(url):
    """The failed checks magi finds when a check named lint failed with url as its log."""
    return github.failed_checks(light_node(PR_TWO, ci="FAILURE", checks=[{"name": "lint", "conclusion": "FAILURE", "detailsUrl": url}]))


def clicks(markup):
    """Each clickable text of the markup, with the action string a click runs."""
    content = to_content(markup)
    found = []
    for span in content.spans:
        style = Style.parse(span.style) if isinstance(span.style, str) else span.style
        if "@click" in style.meta:
            found.append((content.plain[span.start:span.end], style.meta["@click"]))
    return found


@pytest.mark.parametrize("url, opened", [*((url, url) for url in HOSTILE), *((url, CHECKS_PAGE) for url in REJECTED)])
def test_a_failed_check_links_its_log_and_nothing_else(url, opened):
    detail = entries.pr_entry(replace(PR_TWO, ci="failing", failed_checks=failed_check(url)), {}, STATED).detail
    found = clicks(detail)
    assert [parse(action) for text, action in found if text == "lint"] == [("app", "open_link", (opened,))], \
        "a failed check opens its own https log, or else the pr's checks, as one link"
    assert {parse(action)[1] for _, action in found} <= {"open_link", "open_review"}, "a check url never adds an action of its own"
    assert "failing  lint" in to_content(detail).plain.splitlines(), "a check url never breaks the detail's text"


async def clicked(cache, url):
    opened = []
    pr = replace(PR_TWO, ci="failing", failed_checks=failed_check(url))
    app = magi_app(cache, load=lambda: board([PR_ONE, pr]), opener=opened.append)
    async with started(app) as pilot:
        await pilot.press("4", "j")
        await pilot.pause()
        await app.run_action(next(action for text, action in clicks(app.current().detail) if text == "lint"))
        await pilot.pause()
        assert app.is_running, "clicking a failed check leaves the board running"
    return opened


@pytest.mark.usefixtures("default_theme")
@pytest.mark.parametrize("url, opened", [("https://ci.example/a]x[@click=app.quit()]y", "https://ci.example/a]x[@click=app.quit()]y"),
                                         ("file:///etc/hosts", CHECKS_PAGE)])
def test_clicking_a_failed_check_opens_exactly_its_link(cache, url, opened):
    assert asyncio.run(clicked(cache, url)) == [opened], "a click on a failed check hands open exactly the url its link names"


def test_a_link_never_lets_its_url_add_an_action():
    url = "https://x.example/a'b\"c]x[@click=app.quit()]"
    assert [parse(action) for _, action in clicks(entries.link(url, "x"))] == [("app", "open_link", ("https://x.example/a%27b%22c]x[@click=app.quit()]",))], \
        "a url with both quotes stays one link that opens it, quotes percent-encoded, and never adds an action of its own"
