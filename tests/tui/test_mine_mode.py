import asyncio
from contextlib import asynccontextmanager

import pytest
from textual.widgets import Static

from builders import PR_ONE, PR_TWO, TICKET_DETAIL, bare_board, board, magi_app, make_epic, make_pr, make_ticket, started
from magi.domain.entities import Ticket
from magi.tui import app as app_module
from magi.tui.widgets import Board

ASKED = make_pr(url="https://github.com/acme/app/pull/9", number=9, title="[ACME-9] Asked of me", author={"login": "carol"}, head_ref_oid="z9")


def mine_board():
    team = board([PR_ONE, PR_TWO])
    on_two = {**team["changes"][0], "item": PR_TWO.url, "group": PR_TWO.url, "subject": {**team["changes"][0]["subject"], "url": PR_TWO.url}}
    return {**team, "review_prs": [ASKED], "changes": [*team["changes"], on_two],
            "epics": [*team["epics"], make_epic(key="ACME-200", summary="Not mine")],
            "tickets_by_epic": {**team["tickets_by_epic"], "ACME-200": [make_ticket(key="ACME-5")]}}


def shown(app, key):
    return sorted(entry.copy for entry in app.sections[key])


def highlight(app, key, copy):
    found = app.query_one(f"#list-{key}", Board)
    found.highlighted = next(i for i in range(found.option_count)
                             if found.get_option_at_index(i).id and app.sections[key][int(found.get_option_at_index(i).id)].copy == copy)


@asynccontextmanager
async def in_mine(cache, load=mine_board):
    app = magi_app(cache, load=load)
    async with started(app) as pilot:
        await pilot.press("m")
        await pilot.pause()
        yield app, pilot


@pytest.mark.usefixtures("default_theme")
@pytest.mark.parametrize("key, mine", [("kanban", ["ACME-1", "OPS-7"]), ("prs", sorted([PR_ONE.url, ASKED.url])),
                                       ("changes", [PR_ONE.url]), ("epics", ["ACME-100"])])
def test_mine_shows_my_work(cache, key, mine):
    async def check(cache):
        async with in_mine(cache) as (app, _):
            assert shown(app, key) == mine, f"mine shows only my work in the {key} box"
    asyncio.run(check(cache))


async def mine_leaves_the_factory(cache):
    async with in_mine(cache) as (app, _):
        assert shown(app, "factory") == [entry.copy for entry in app.factory_rows()], "mine leaves the factory as it is"


async def the_header_marks_mine_mode(cache):
    app = magi_app(cache, load=mine_board)
    async with started(app) as pilot:
        assert not app.query_one("#mine").display, "the header tells nothing while the whole team shows"
        await pilot.press("m")
        assert app.query_one("#mine").display, "the header tells mine mode is on"
        await pilot.press("m")
        assert not app.query_one("#mine").display, "the header drops the mine mark when the whole team shows"


async def m_again_shows_the_whole_team(cache):
    app = magi_app(cache, load=mine_board)
    async with started(app) as pilot:
        team = {key: shown(app, key) for key in ("kanban", "prs", "changes", "epics")}
        await pilot.press("m", "m")
        await pilot.pause()
        assert {key: shown(app, key) for key in team} == team, "m again shows the whole team"


async def mine_keeps_the_row(cache):
    app = magi_app(cache, load=mine_board)
    async with started(app) as pilot:
        await pilot.press("2")
        highlight(app, "prs", PR_ONE.url)
        await pilot.press("m")
        await pilot.pause()
        assert app.current().url == PR_ONE.url, "mine keeps the highlighted row while its item still shows"


@pytest.mark.usefixtures("default_theme")
@pytest.mark.parametrize("url, mine", [(PR_TWO.url, False), (ASKED.url, True)])
def test_a_snooze_survives_mine_mode(cache, url, mine):
    async def check(cache):
        app = magi_app(cache, load=mine_board)
        async with started(app) as pilot:
            await pilot.press(*["m"] * mine, "2")
            highlight(app, "prs", url)
            await pilot.press("s", "m", "m")
            await pilot.pause()
            assert url in app.snoozed["prs"], "a snooze holds across mine mode, also on a pr asking for my review off the team board"
    asyncio.run(check(cache))


async def waking_in_mine_wakes_only_my_snoozes(cache):
    app = magi_app(cache, load=mine_board)
    async with started(app) as pilot:
        await pilot.press("2")
        for url in (PR_TWO.url, PR_ONE.url):
            highlight(app, "prs", url)
            await pilot.press("s")
        await pilot.press("m", "S")
        await pilot.pause()
        assert list(app.snoozed["prs"]) == [PR_TWO.url], "S in mine mode wakes the snoozes of my box and leaves the team's"


async def my_ticket_cached_before_its_detail(cache):
    async with in_mine(cache) as (app, pilot):
        await pilot.press("1")
        highlight(app, "kanban", "OPS-7")
        await pilot.pause()
        detail = str(app.query_one("#detail", Static).render())
        assert "creator" not in detail and "epic" not in detail, "a ticket cached before the detail fetch shows no detail fields"


async def reviewing_my_ticket_cached_before_its_detail(cache):
    async with in_mine(cache) as (app, pilot):
        await pilot.press("1")
        highlight(app, "kanban", "OPS-7")
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        assert not isinstance(app.screen, app_module.ReviewScreen), "c on a ticket cached before the detail fetch opens nothing"
        assert any("no review comments" in n.message for n in app._notifications), "c on a ticket cached before the detail fetch says so"


def ranked_board():
    ticket = lambda key: Ticket(key=key, summary=key, status="En proceso", assignee="Ana", detail=TICKET_DETAIL)
    return {**board([PR_ONE]), "kanban": [ticket("ACME-1"), ticket("ACME-2")], "my_tickets": [ticket("ACME-2"), ticket("ACME-1")]}


async def mine_keeps_the_jira_rank(cache):
    async with in_mine(cache, load=ranked_board) as (app, _):
        assert [entry.copy for entry in app.sections["kanban"]] == ["ACME-1", "ACME-2"], "my tickets on the board keep their Jira rank in mine mode"


async def mine_with_nothing_of_mine(cache):
    async with in_mine(cache, load=lambda: bare_board(prs=[PR_TWO], epics=[make_epic()], tickets_by_epic={"ACME-100": []})) as (app, _):
        assert all(app.sections[key] == [] for key in ("kanban", "prs", "changes", "epics")), "with nothing of mine, mine mode empties the boxes"


@pytest.mark.usefixtures("default_theme")
def test_mine_leaves_the_factory(cache):
    asyncio.run(mine_leaves_the_factory(cache))


@pytest.mark.usefixtures("default_theme")
def test_the_header_marks_mine_mode(cache):
    asyncio.run(the_header_marks_mine_mode(cache))


@pytest.mark.usefixtures("default_theme")
def test_m_again_shows_the_whole_team(cache):
    asyncio.run(m_again_shows_the_whole_team(cache))


@pytest.mark.usefixtures("default_theme")
def test_mine_keeps_the_row(cache):
    asyncio.run(mine_keeps_the_row(cache))


@pytest.mark.usefixtures("default_theme")
def test_waking_in_mine_wakes_only_my_snoozes(cache):
    asyncio.run(waking_in_mine_wakes_only_my_snoozes(cache))


@pytest.mark.usefixtures("default_theme")
def test_my_ticket_cached_before_its_detail(cache):
    asyncio.run(my_ticket_cached_before_its_detail(cache))


@pytest.mark.usefixtures("default_theme")
def test_mine_with_nothing_of_mine(cache):
    asyncio.run(mine_with_nothing_of_mine(cache))


@pytest.mark.usefixtures("default_theme")
def test_reviewing_my_ticket_cached_before_its_detail(cache):
    asyncio.run(reviewing_my_ticket_cached_before_its_detail(cache))


@pytest.mark.usefixtures("default_theme")
def test_mine_keeps_the_jira_rank(cache):
    asyncio.run(mine_keeps_the_jira_rank(cache))
