import asyncio
import json

import pytest
from textual.widgets import OptionList, Tab

from builders import PR_ONE, PR_TWO, SUBJECT, board, magi_app, started
from magi.adapters import storage

BOXES = ("attention", "prs", "changes", "mine_prs")


def two_prs():
    return board([PR_ONE, PR_TWO])


def rows(app, box):
    found = app.query_one(f"#list-{box}", OptionList)
    return [found.get_option_at_index(i).prompt.plain for i in range(found.option_count) if found.get_option_at_index(i).id]


def marked(app):
    return {box: [row.startswith("● ") for row in rows(app, box)] for box in BOXES}


async def unseen(cache):
    storage.write(cache.with_name("seen.json"), {"seen": {"https://github.com/acme/app/pull/99": "2026-10-20T10:00 Merged"}})
    app = magi_app(cache, load=two_prs)
    async with started(app) as pilot:
        assert marked(app) == {"attention": [True], "prs": [True, False], "changes": [True], "mine_prs": [True]}, \
            "every row of an item with an unseen change carries a dot, in every box"
        assert str(app.query_one("#panel-prs").border_title) == "[4] team prs 2 · 1 new", "a box counts its unseen rows"
        assert str(app.query_one("#panel-epics").border_title) == "[6] epics 1", "a box with nothing new shows no count"
        assert [str(app.query_one(f"#tab-{tab}", Tab).label) for tab in ("overview", "mine")] == ["[1] Overview ●", "[2] Mine ●"], \
            "a tab with unseen rows carries a dot"
        await pilot.press("4")
        await pilot.pause()
        assert str(app.query_one("#detail").render()).startswith("● New PR · 02:04"), "the detail opens with the unseen change"
        assert marked(app)["prs"] == [True, False], "the dot stays while the cursor is on the row"
        await pilot.press("j")
        await pilot.pause()
        assert marked(app) == {"attention": [False], "prs": [False, False], "changes": [False], "mine_prs": [False]}, \
            "leaving the row clears its dot in every box"
        assert str(app.query_one("#panel-prs").border_title) == "[4] team prs 2", "leaving the row drops the box's new count"
        assert [str(app.query_one(f"#tab-{tab}", Tab).label) for tab in ("overview", "mine")] == ["[1] Overview", "[2] Mine"], \
            "leaving the row clears the tabs' dots"
        assert not str(app.query_one("#detail").render()).startswith("●"), "a seen change leaves the detail as it was"
    assert storage.read(cache.with_name("seen.json")) == {"seen": {PR_ONE.url: "2026-10-24T02:04 New PR"}}, \
        "what was seen is saved, and items no longer on the board are dropped"
    app = magi_app(cache, load=two_prs)
    async with started(app) as pilot:
        assert not any(any(row) for row in marked(app).values()), "a seen change stays seen after a restart"


async def changed_twice(cache):
    storage.write(cache.with_name("seen.json"), {"seen": {PR_ONE.url: "2026-10-24T02:04 New PR"}})
    found = two_prs()
    found["changes"] = [{**found["changes"][0], "at": "2026-10-25T03:00", "tone": "approved", "label": "Approved"}, *found["changes"]]
    app = magi_app(cache, load=lambda: found)
    async with started(app) as pilot:
        assert marked(app)["prs"] == [True, False], "an item's newest change decides whether it is new"
        await pilot.press("4")
        await pilot.pause()
        assert str(app.query_one("#detail").render()).startswith("● New PR · 03:00"), \
            "the detail opens with the item's newest change, a pr new in the window still a new pr"


@pytest.mark.usefixtures("default_theme")
def test_an_item_changed_twice_shows_its_newest_change(cache):
    asyncio.run(changed_twice(cache))


@pytest.mark.usefixtures("default_theme")
def test_unseen_changes(cache):
    asyncio.run(unseen(cache))


async def first_run(cache):
    app = magi_app(cache, load=two_prs)
    async with started(app) as pilot:
        assert not any(any(row) for row in marked(app).values()), "the first run marks nothing"
    assert storage.read(cache.with_name("seen.json")) == {"seen": {PR_ONE.url: "2026-10-24T02:04 New PR"}}, \
        "the first run takes every change as seen"


@pytest.mark.usefixtures("default_theme")
def test_first_run_marks_nothing(cache):
    asyncio.run(first_run(cache))


async def upgraded(cache):
    cache.with_name("seen.json").write_text(json.dumps({"version": 4, "seen": {PR_ONE.url: "2026-10-23T01:00 Old change"}}))
    app = magi_app(cache, load=two_prs)
    async with started(app):
        assert marked(app)["prs"] == [True, False], "marks seen before an upgrade keep an unread change unread"


@pytest.mark.usefixtures("default_theme")
def test_seen_marks_saved_by_format_4_survive_the_upgrade(cache):
    asyncio.run(upgraded(cache))


async def lcars_unseen(cache):
    storage.write(cache.with_name("seen.json"), {"seen": {}})
    app = magi_app(cache, load=two_prs, theme="okuda")
    async with started(app) as pilot:
        assert marked(app)["prs"][0], "LCARS marks unseen rows too"
        assert str(app.query_one("#panel-prs .count").render()) == "2 · 1 new", "LCARS counts unseen rows in the title pill"
        assert "●" in str(app.query_one("#pill-mine .seg").render()), "LCARS marks a tab pill with unseen rows"


@pytest.mark.usefixtures("default_theme")
def test_lcars_unseen_changes(cache):
    asyncio.run(lcars_unseen(cache))


def with_change(item, at, label):
    found = two_prs()
    found["changes"] = [*found["changes"], {"at": at, "tone": "commented", "label": label, "subject": {**SUBJECT, "url": item},
                                            "note": None, "aside": None, "told": False, "item": item, "group": item}]
    return found


async def refresh_on_a_row(cache):
    loaded = {"board": two_prs()}
    app = magi_app(cache, load=lambda: loaded["board"])
    async with started(app) as pilot:
        await pilot.press("4", "j")
        await pilot.pause()
        loaded["board"] = with_change(PR_TWO.url, "2026-10-25T03:00", "New commits")
        app.start_refresh()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert marked(app)["prs"] == [False, True], "a refresh does not count as leaving the row the cursor sat on"
    assert PR_TWO.url not in storage.read(cache.with_name("seen.json"))["seen"], "a change the refresh brought stays unseen"


@pytest.mark.usefixtures("default_theme")
def test_a_refresh_keeps_new_changes_unseen(cache):
    asyncio.run(refresh_on_a_row(cache))


async def changed_again(cache):
    storage.write(cache.with_name("seen.json"), {"seen": {PR_ONE.url: "2026-10-23T01:00 Old change"}})
    app = magi_app(cache, load=two_prs)
    async with started(app) as pilot:
        assert marked(app)["prs"] == [True, False], "an item that changed again after it was seen is marked again"
        await pilot.press("4", "j")
        await pilot.pause()
    assert storage.read(cache.with_name("seen.json")) == {"seen": {PR_ONE.url: "2026-10-24T02:04 New PR"}}, \
        "leaving the row saves its latest change as seen"


@pytest.mark.usefixtures("default_theme")
def test_a_seen_item_that_changes_again_is_marked(cache):
    asyncio.run(changed_again(cache))


async def moving_between(cache):
    storage.write(cache.with_name("seen.json"), {"seen": {}})
    app = magi_app(cache, load=lambda: with_change(PR_TWO.url, "2026-10-25T03:00", "[bold]Re-review[/bold]"))
    async with started(app) as pilot:
        await pilot.press("4", "j")
        await pilot.pause()
        assert marked(app)["prs"] == [False, True], "moving between two unseen rows marks only the one left"
        assert str(app.query_one("#detail").render()).startswith("● [bold]Re-review[/bold] · 03:00"), \
            "the detail shows a change's label as written"
        await pilot.press("3")
        await pilot.pause()
        assert marked(app)["prs"] == [False, False], "leaving a row for another box marks it seen"


@pytest.mark.usefixtures("default_theme")
def test_moving_between_rows_and_boxes(cache):
    asyncio.run(moving_between(cache))


async def filtering(cache):
    storage.write(cache.with_name("seen.json"), {"seen": {}})
    app = magi_app(cache, load=two_prs)
    async with started(app) as pilot:
        await pilot.press("4", "slash", *"second", "escape")
        await pilot.pause()
        assert marked(app)["prs"] == [True, False], "a filter that hides the cursor's row does not mark it seen"


@pytest.mark.usefixtures("default_theme")
def test_a_filter_keeps_the_row_unseen(cache):
    asyncio.run(filtering(cache))
