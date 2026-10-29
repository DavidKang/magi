import asyncio
import json

import pytest
from textual.widgets import OptionList

from builders import PR_ONE, PR_TWO, STATED, board, failing_load, magi_app, started
from magi.adapters import storage
from magi.domain.changes import ticket_subject


def two_prs():
    return board([PR_ONE, PR_TWO])


def approved():
    found = two_prs()
    found["changes"] = [{**found["changes"][0], "at": "2026-10-25T03:00", "tone": "approved", "label": "Approved"}, *found["changes"]]
    return found


def rows(app, box):
    found = app.query_one(f"#list-{box}", OptionList)
    return [found.get_option_at_index(i).prompt.plain for i in range(found.option_count) if found.get_option_at_index(i).id]


def snoozed(cache):
    return storage.read(cache.with_name("snoozed.json"))["snoozed"]


async def snooze_until_it_changes(cache):
    app = magi_app(cache, load=two_prs)
    async with started(app) as pilot:
        await pilot.press("2", "s")
        await pilot.pause()
        assert len(rows(app, "prs")) == 1, "s hides the selected team pr"
        assert str(app.query_one("#panel-prs").border_title) == "[2] team prs 1 · 1 snoozed", "a box counts its snoozed items"
        assert len(rows(app, "changes")) == 1, "a snooze hides the item in its own box only"
    assert snoozed(cache) == {"prs": {PR_ONE.url: "2026-10-24T02:04 New PR"}}, "a snooze keeps the item's newest change"
    app = magi_app(cache, load=two_prs)
    async with started(app):
        assert len(rows(app, "prs")) == 1, "a snoozed item stays hidden after a restart while nothing changes on it"
    app = magi_app(cache, load=approved, clock=lambda: 2000.0)
    async with started(app):
        assert len(rows(app, "prs")) == 2, "a change newer than the snooze brings the item back"
        assert str(app.query_one("#panel-prs").border_title) == "[2] team prs 2 · 1 new", \
            "a woken item leaves the snoozed count, and the change that woke it is new"
    assert snoozed(cache) == {"prs": {}}, "a woken item drops its snooze"


@pytest.mark.usefixtures("default_theme")
def test_a_snooze_lasts_until_the_item_changes(cache):
    asyncio.run(snooze_until_it_changes(cache))


async def snoozed_before_an_upgrade(cache):
    cache.with_name("snoozed.json").write_text(json.dumps({"version": storage.VERSION - 1,
                                                           "snoozed": {"prs": {PR_ONE.url: "2026-10-24T02:04 New PR"}}}))
    app = magi_app(cache, load=two_prs)
    async with started(app):
        assert len(rows(app, "prs")) == 1, \
            "a snooze saved by the storage version before survives the upgrade: a storage bump fails here until KEPT_UPGRADES keeps it"


@pytest.mark.usefixtures("default_theme")
def test_snoozes_saved_by_the_last_format_survive_the_upgrade(cache):
    asyncio.run(snoozed_before_an_upgrade(cache))


async def wake_the_box(cache):
    app = magi_app(cache, load=two_prs)
    async with started(app) as pilot:
        await pilot.press("2", "s")
        await pilot.pause()
        assert ["[ACME-2]" in row for row in rows(app, "prs")] == [True], "s hides the selected team pr"
        await pilot.press("S")
        await pilot.pause()
        assert len(rows(app, "prs")) == 2, "S brings back every snoozed item of the box"
        await pilot.press("4", "s")
        await pilot.pause()
        assert len(rows(app, "epics")) == 1, "only team prs snooze"
    assert snoozed(cache) == {"prs": {}}, "S saves the box with no snoozes"


@pytest.mark.usefixtures("default_theme")
def test_shift_s_wakes_the_box(cache):
    asyncio.run(wake_the_box(cache))


def notified(app, text):
    return any(text in n.message for n in app._notifications)


async def boxes_that_do_not_snooze(cache):
    app = magi_app(cache, load=two_prs)
    async with started(app) as pilot:
        for box in ("1", "3", "4"):
            await pilot.press(box, "s")
            await pilot.pause()
        assert notified(app, "only team prs snooze"), "s says which boxes snooze"
        assert [len(rows(app, box)) for box in ("kanban", "changes", "epics")] == [1, 1, 1], "s hides nothing in a box that does not snooze"
    assert not cache.with_name("snoozed.json").exists(), "s in a box that does not snooze saves nothing"


@pytest.mark.usefixtures("default_theme")
def test_only_team_prs_snooze(cache):
    asyncio.run(boxes_that_do_not_snooze(cache))


async def before_the_board(cache):
    app = magi_app(cache, load=failing_load)
    async with started(app) as pilot:
        await pilot.press("S", "s")
        await pilot.pause()
        assert app.is_running, "s and S before the first board do nothing"
    assert not cache.with_name("snoozed.json").exists(), "s and S before the first board save nothing"


@pytest.mark.usefixtures("default_theme")
def test_snooze_keys_wait_for_the_board(cache):
    asyncio.run(before_the_board(cache))


async def empty_box(cache):
    async with started(magi_app(cache, load=lambda: board([]))) as pilot:
        await pilot.press("2", "s")
        await pilot.pause()
    assert not cache.with_name("snoozed.json").exists(), "s in an empty box snoozes nothing"


@pytest.mark.usefixtures("default_theme")
def test_s_in_an_empty_box(cache):
    asyncio.run(empty_box(cache))


async def quiet_pr(cache):
    async with started(magi_app(cache, load=lambda: {**two_prs(), "changes": []})) as pilot:
        await pilot.press("2", "s")
        await pilot.pause()
    assert snoozed(cache) == {"prs": {PR_ONE.url: None}}, "a pr snoozed with no change keeps no mark until one comes"


@pytest.mark.usefixtures("default_theme")
def test_s_on_a_quiet_pr(cache):
    asyncio.run(quiet_pr(cache))


def ticket_moved():
    found = two_prs()
    moved = {"at": "2026-10-25T04:00", "tone": "approved", "label": "Done", "note": None, "aside": "was: In Progress", "told": False,
             "subject": ticket_subject("ACME-1", STATED.jira_browse, "Ticket one"), "item": STATED.jira_browse + "ACME-1", "group": PR_ONE.url}
    found["changes"] = [moved, *found["changes"]]
    return found


async def woken_by_its_ticket(cache):
    app = magi_app(cache, load=two_prs)
    async with started(app) as pilot:
        await pilot.press("2", "s")
        await pilot.pause()
        assert len(rows(app, "prs")) == 1, "s hides the selected team pr"
    app = magi_app(cache, load=ticket_moved, clock=lambda: 2000.0)
    async with started(app):
        assert len(rows(app, "prs")) == 2, "a move of the pr's ticket brings the snoozed pr back"
    assert snoozed(cache) == {"prs": {}}, "a pr woken by its ticket drops its snooze"


@pytest.mark.usefixtures("default_theme")
def test_a_ticket_move_wakes_its_pr(cache):
    asyncio.run(woken_by_its_ticket(cache))
