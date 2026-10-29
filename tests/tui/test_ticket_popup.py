import asyncio
import subprocess
import threading
from dataclasses import replace

import pytest
from textual.widgets import Static

from builders import PR_ONE, PR_TWO, TICKET_DETAIL, board, magi_app, make_pr, started
from magi.domain.entities import Ticket
from magi.tui import app as app_module

NO_TICKET = make_pr(url="https://github.com/acme/app/pull/3", number=3, title="Bump deps", head_ref_name="deps",
                    created_at="2026-10-24T10:00:00Z", head_ref_oid="c3")


async def until(pilot, done, rule):
    for _ in range(500):
        if done():
            return
        await pilot.pause(0.01)
    assert done(), rule


async def ticket_popup(cache):
    fetched = []

    def fetch_ticket(key):
        fetched.append(key)
        return Ticket(key=key, summary=f"Summary of {key}", status="En revisión", detail=TICKET_DETAIL)

    opened, copied = [], []
    app = magi_app(cache, load=lambda: board([PR_ONE, NO_TICKET, PR_TWO]), fetch_ticket=fetch_ticket, opener=opened.append, copier=copied.append)
    async with started(app) as pilot:
        await pilot.press("2", "v")
        await until(pilot, lambda: isinstance(app.screen, app_module.TicketScreen), "v opens the ticket of the selected PR in a popup")
        assert fetched == ["ACME-1"], "v asks Jira for the ticket the PR names"
        assert "ACME-1" in str(app.screen.query_one("#ticket").border_title), "the popup title names the ticket"
        detail = str(app.screen.query_one("#ticket-detail", Static).render())
        assert "Summary of ACME-1" in detail and "In review" in detail, "the popup shows the ticket detail, as the ticket box does"
        await pilot.press("c")
        assert isinstance(app.screen, app_module.ReviewScreen), "c in the popup opens the ticket's description and comments"
        assert "ACME-1" in str(app.screen.query_one("#review").border_title), "c in the popup opens the ticket's comments, not the PR's"
        await pilot.press("escape", "escape")
        assert not isinstance(app.screen, (app_module.TicketScreen, app_module.ReviewScreen)), "escape closes the popups"
        await pilot.press("v")
        await until(pilot, lambda: isinstance(app.screen, app_module.TicketScreen), "v opens a ticket already seen")
        await pilot.press("enter", "y")
        assert opened == ["https://acme.atlassian.net/browse/ACME-1"], "enter in the popup opens the ticket in Jira"
        assert copied == ["ACME-1"], "y in the popup copies the ticket key"
        await pilot.press("v")
        assert not isinstance(app.screen, app_module.TicketScreen), "v closes the ticket popup"
        await pilot.press("j", "v")
        await pilot.pause()
        assert any(n.message == "no ticket" for n in app._notifications), "v on a PR without a ticket says so"
        assert fetched == ["ACME-1", "ACME-1"], "v on a PR without a ticket asks Jira nothing"


@pytest.mark.usefixtures("default_theme")
def test_ticket_popup(cache):
    asyncio.run(ticket_popup(cache))


async def failed_ticket(cache):
    def fetch_ticket(key):
        raise subprocess.CalledProcessError(1, ["acli"], stderr="ACME-1 not found\n")

    app = magi_app(cache, fetch_ticket=fetch_ticket)
    async with started(app) as pilot:
        await pilot.press("2", "v")
        await until(pilot, lambda: any(n.message == "ACME-1 not found" for n in app._notifications), "a ticket Jira cannot give says why")
        assert not isinstance(app.screen, app_module.TicketScreen), "a ticket Jira cannot give opens no popup"


def test_failed_ticket(cache):
    asyncio.run(failed_ticket(cache))


async def slow_ticket(cache):
    fetched, release = [], threading.Event()

    def fetch_ticket(key):
        fetched.append(key)
        release.wait(5)
        return Ticket(key=key, summary="Bare", status="En proceso", detail=replace(TICKET_DETAIL, description="", comments=[]))

    app = magi_app(cache, fetch_ticket=fetch_ticket)
    async with started(app) as pilot:
        try:
            await pilot.press("2", "v", "v", "t")
            assert fetched == ["ACME-1"], "v while its ticket loads asks Jira nothing more"
        finally:
            release.set()
        await pilot.pause(0.2)
        assert isinstance(app.screen, app_module.ThemeScreen), "a ticket that arrives while another popup is open does not cover it"
        await pilot.press("escape", "v")
        await until(pilot, lambda: isinstance(app.screen, app_module.TicketScreen), "v opens the ticket once no other popup is open")
        await pilot.press("c")
        assert any(n.message == "no comments" for n in app._notifications), "c in the ticket popup on a ticket with nothing to read says so"


@pytest.mark.usefixtures("default_theme")
def test_slow_ticket(cache):
    asyncio.run(slow_ticket(cache))
