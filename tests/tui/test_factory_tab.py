import asyncio
import datetime as dt
import re
import threading
from types import SimpleNamespace

from textual.widgets import OptionList, Static, Tabs

from builders import failing_load, magi_app, pick_theme, started
from magi.domain.factory import FactoryTicket
from magi.tui import app as app_module

NOW = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.timezone.utc)
TICKETS = [FactoryTicket("ACME-77", "waiting-you", "which repo?", NOW - dt.timedelta(minutes=5), None),
           FactoryTicket("ACME-78", "ready", "", NOW - dt.timedelta(hours=2), "done", "w2H:p2")]
BOARD_BOXES = ["attention", "prs", "changes", "epics", "mine_prs", "mine_tickets"]


def factory_app(cache, factory=lambda: TICKETS):
    return magi_app(cache, factory=factory, clock=NOW.timestamp)


async def factory_tab(cache):
    app = factory_app(cache)
    async with started(app) as pilot:
        await pilot.press("9")
        await pilot.pause()
        rows = app.query_one("#list-factory", OptionList)
        shown = [rows.get_option_at_index(i).prompt.plain for i in range(rows.option_count)]
        assert app.query_one(Tabs).active == "tab-factory", "9 opens the factory tab"
        assert len(shown) == 2 and "ACME-77" in shown[0] and "ACME-78" in shown[1], \
            "the factory tab lists one row per factory ticket, in the order the factory gives"
        assert "which repo?" in str(app.query_one("#detail", Static).render()), "the focused factory row shows its details"
        assert str(app.query_one("#panel-factory").border_title) == "[9] factory 2", "the factory box is numbered 9 and counts its tickets"
        await pilot.press("3")
        assert app.query_one(Tabs).active == "tab-overview", "the board's boxes keep their keys beside the factory"


def test_factory_tab(cache):
    asyncio.run(factory_tab(cache))


async def factory_reread_keeps_the_row(cache):
    app = factory_app(cache)
    async with started(app) as pilot:
        await pilot.press("9", "j")
        app.read_factory()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.current().copy == "ACME-78", "reading the factory again every few seconds keeps the row you are on"


def counted(*answers):
    """A factory answering each read in turn, then its last answer again; calls counts the reads."""
    calls = []

    def factory():
        calls.append(1)
        return answers[min(len(calls), len(answers)) - 1]
    return factory, calls


def shown_rows(app):
    rows = app.query_one("#list-factory", OptionList)
    return [rows.get_option_at_index(i).prompt.plain for i in range(rows.option_count)]


async def factory_reread_without_changes_keeps_the_box(cache):
    factory, calls = counted(TICKETS)
    app = factory_app(cache, factory=factory)
    async with started(app) as pilot:
        await pilot.press("9")
        await app.workers.wait_for_complete()
        drawn = []
        fill = app.fill
        app.fill = lambda key: (drawn.append(key), fill(key))
        app.read_factory()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(calls) == 2, "the factory is read again"
        assert "factory" not in drawn, "a factory that did not change is not redrawn every few seconds"


async def factory_reread_with_changes_redraws_the_box(cache):
    factory, calls = counted(TICKETS, TICKETS[:1])
    app = factory_app(cache, factory=factory)
    async with started(app) as pilot:
        await pilot.press("9")
        await app.workers.wait_for_complete()
        app.read_factory()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(calls) == 2 and len(shown_rows(app)) == 1 and "ACME-77" in shown_rows(app)[0], \
            "a factory whose tickets changed is redrawn with its new rows"


def test_factory_reread_with_changes_redraws_the_box(cache):
    asyncio.run(factory_reread_with_changes_redraws_the_box(cache))


async def factory_read_one_at_a_time(cache):
    entered, release, calls = threading.Event(), threading.Event(), []

    def factory():
        calls.append(1)
        if len(calls) > 1:
            entered.set()
            release.wait(5)
        return TICKETS
    app = factory_app(cache, factory=factory)
    async with started(app) as pilot:
        app.read_factory()
        await asyncio.to_thread(entered.wait, 5)
        app.read_factory()
        await asyncio.sleep(0.1)
        assert len(calls) == 2, "a factory read still running is not started again: a hanging herdr never piles up threads"
        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()


def test_factory_read_one_at_a_time(cache):
    asyncio.run(factory_read_one_at_a_time(cache))


async def empty_factory_without_a_board(cache):
    app = magi_app(cache, load=failing_load, factory=list, clock=NOW.timestamp)
    async with started(app) as pilot:
        await pilot.press("9")
        await pilot.pause()
        assert app.board is None and shown_rows(app) == ["no factory tickets"], \
            "an empty factory says so on a cold start, before the board ever loads"


def test_empty_factory_without_a_board(cache):
    asyncio.run(empty_factory_without_a_board(cache))


async def theme_redraws_the_factory_without_a_board(cache):
    app = magi_app(cache, load=failing_load, factory=lambda: TICKETS, clock=NOW.timestamp, theme="nerv")
    async with started(app) as pilot:
        await pilot.press("9")
        await pilot.pause()
        before = [str(span.style) for span in app.query_one("#list-factory", OptionList).get_option_at_index(0).prompt.spans]
        await pick_theme(pilot, "cyberpunk")
        app.read_factory()
        await app.workers.wait_for_complete()
        await pilot.pause()
        after = [str(span.style) for span in app.query_one("#list-factory", OptionList).get_option_at_index(0).prompt.spans]
        assert app.board is None and after != before, "a new theme repaints the factory's unchanged rows, even before the board loads"


def test_theme_redraws_the_factory_without_a_board(cache):
    asyncio.run(theme_redraws_the_factory_without_a_board(cache))


def test_factory_reread_without_changes_keeps_the_box(cache):
    asyncio.run(factory_reread_without_changes_keeps_the_box(cache))


def test_factory_reread_keeps_the_row(cache):
    asyncio.run(factory_reread_keeps_the_row(cache))


async def factory_redraw_marks_nothing_seen(cache):
    changed = [TICKETS[0], FactoryTicket("ACME-78", "ready", "merged", NOW - dt.timedelta(hours=2), "done")]
    factory, _ = counted(TICKETS, changed)
    app = factory_app(cache, factory=factory)
    async with started(app) as pilot:
        await pilot.press("9", "j")
        first = app.settings.jira_browse + "ACME-77"
        app.news[first] = {"at": "2026-10-29T11:00:00", "label": "In review"}
        app.read_factory()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.current().copy == "ACME-78" and first in app.news, \
            "a factory redraw that keeps you on your row does not mark the first row's news as seen"


def test_factory_redraw_marks_nothing_seen(cache):
    asyncio.run(factory_redraw_marks_nothing_seen(cache))


async def factory_counts_without_a_board(cache):
    app = magi_app(cache, load=failing_load, factory=lambda: TICKETS, clock=NOW.timestamp)
    async with started(app) as pilot:
        await pilot.press("9")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.board is None and str(app.query_one("#panel-factory").border_title) == "[9] factory 2", \
            "the factory box counts its tickets as soon as the factory is read, before the board ever loads"


def test_factory_counts_without_a_board(cache):
    asyncio.run(factory_counts_without_a_board(cache))


async def factory_stays_out_of_the_web_page(cache):
    async with started(factory_app(cache)):
        pass
    found = cache.with_name("board.html").read_text()
    assert "ACME-77" not in found and 'id="factory"' not in found and 'href="#factory"' not in found, \
        "the factory lives only in the tui: magi web's page never lists it"
    assert re.findall(r'<section id="([a-z_]+)"', found) == [*BOARD_BOXES, "details"], \
        "the web page still shows the board's boxes, the same ones as before the factory"


def test_factory_stays_out_of_the_web_page(cache):
    asyncio.run(factory_stays_out_of_the_web_page(cache))


def broken_factory():
    raise RuntimeError("disk gone")


async def factory_failure_keeps_the_board(cache):
    app = factory_app(cache, factory=broken_factory)
    async with started(app) as pilot:
        await pilot.press("9")
        await pilot.pause()
        rows = app.query_one("#list-factory", OptionList)
        assert rows.get_option_at_index(0).prompt.plain == "no factory tickets", "a factory that cannot be read shows an empty box"
        assert app.board is not None, "a factory that cannot be read never stops the board"


def test_factory_failure_keeps_the_board(cache):
    asyncio.run(factory_failure_keeps_the_board(cache))


async def factory_failure_keeps_its_rows(cache):
    reads = []

    def factory():
        reads.append(1)
        return TICKETS if len(reads) == 1 else broken_factory()
    app = factory_app(cache, factory=factory)
    async with started(app) as pilot:
        await pilot.press("9")
        await app.workers.wait_for_complete()
        app.read_factory()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(reads) == 2 and len(shown_rows(app)) == 2 and "ACME-77" in shown_rows(app)[0], \
            "a factory that fails after a good read keeps the rows it showed"


def test_factory_failure_keeps_its_rows(cache):
    asyncio.run(factory_failure_keeps_its_rows(cache))


async def lcars_factory_pill(cache):
    app = magi_app(cache, factory=lambda: TICKETS, clock=NOW.timestamp, theme="okuda")
    async with started(app) as pilot:
        await pilot.click("#pill-factory")
        await pilot.pause()
        assert (app.current_section, app.query_one(Tabs).active) == ("factory", "tab-factory"), "the factory's lcars pill shows its tab"
        assert [pill.has_class("-on") for pill in app.query(".tab-pill")] == [False, False, True], "the factory's pill lights up once its tab shows"


def test_lcars_factory_pill(cache):
    asyncio.run(lcars_factory_pill(cache))


class InlineThread:
    """Runs its target on start, so a test reads what a key did without waiting on a thread."""

    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


async def g_presses(cache, monkeypatch, *keys, tickets=TICKETS):
    monkeypatch.setattr(app_module, "threading", SimpleNamespace(Thread=InlineThread))
    focused = []
    app = magi_app(cache, factory=lambda: tickets, clock=NOW.timestamp, focus_session=focused.append)
    async with started(app) as pilot:
        await pilot.press(*keys)
        await pilot.pause()
    return focused


def test_g_jumps_to_the_session(cache, monkeypatch):
    assert asyncio.run(g_presses(cache, monkeypatch, "9", "j", "g")) == ["w2H:p2"], "g on a factory row jumps to its herdr session"


def test_g_without_a_session_does_nothing(cache, monkeypatch):
    assert asyncio.run(g_presses(cache, monkeypatch, "9", "g")) == [], "g on a factory row without a session does nothing"


def test_g_outside_the_factory_does_nothing(cache, monkeypatch):
    # The epics box's first row is ACME-100: a factory ticket with that key must not make g jump from there.
    tickets = [FactoryTicket("ACME-100", "building", "", NOW, "working", "w1:p1")]
    assert asyncio.run(g_presses(cache, monkeypatch, "9", "6", "g", tickets=tickets)) == [], "g outside the factory does nothing"


async def g_waits_behind_a_popup(cache):
    app = factory_app(cache)
    async with started(app) as pilot:
        await pilot.press("9", "j", "t")
        await pilot.pause()
        assert not app.check_action("focus_session", ()), "a popup blocks g, as it blocks every board key"


def test_g_waits_behind_a_popup(cache):
    asyncio.run(g_waits_behind_a_popup(cache))
