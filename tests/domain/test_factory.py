import datetime as dt

from magi.domain.factory import Agent, Stage, factory_tickets, session_of

UTC = dt.timezone.utc
AT = dt.datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


def stage(key, name="building", detail="", since=AT):
    return Stage(key, name, detail, since)


def test_a_ticket_finds_its_session_by_the_worktree_it_runs_in():
    agents = [Agent("storefront", "idle"), Agent("ACME-12", "working"), Agent("ACME-7-fix-the-rounding", "done")]
    assert session_of("ACME-12", agents) == "working", "a ticket's session is the agent whose worktree folder is named after the key"
    assert session_of("ACME-7", agents) == "done", "a worktree named after the key and a slug is the ticket's session too"
    assert session_of("ACME-1", agents) is None, "ACME-1 is not ACME-12: a key matches the whole folder name or the key and a dash"


def test_two_agents_in_one_worktree_give_the_first_listed():
    agents = [Agent("ACME-12", "idle"), Agent("ACME-12-retry", "working")]
    assert session_of("ACME-12", agents) == "idle", "when two herdr agents work on one ticket, its session is the first herdr lists"


def test_a_ticket_without_a_session_shows_it_absent():
    found = factory_tickets([stage("ACME-3")], [Agent("ACME-4", "working")])
    assert [(ticket.key, ticket.agent) for ticket in found] == [("ACME-3", None)], "a ticket no herdr agent works on has no session"


def test_a_ticket_carries_its_stage_detail_and_when_it_changed():
    [ticket] = factory_tickets([stage("ACME-5", "waiting-you", "which repo?")], [])
    assert (ticket.stage, ticket.detail, ticket.since) == ("waiting-you", "which repo?", AT), \
        "each factory ticket reads its stage, its detail and when its stage changed"


def test_stages_the_factory_never_writes_are_left_out():
    found = factory_tickets([stage("ACME-1"), stage("ACME-3", "shipped")], [])
    assert [ticket.key for ticket in found] == ["ACME-1"], "a stage the factory never writes is not a factory ticket"


def test_tickets_needing_you_come_first():
    found = factory_tickets([stage("ACME-1", "ready"), stage("ACME-2", "building"), stage("ACME-3", "review-blocked"), stage("ACME-4", "waiting-you"),
                             stage("ACME-0", "building")], [])
    assert [ticket.key for ticket in found] == ["ACME-4", "ACME-3", "ACME-0", "ACME-2", "ACME-1"], \
        "tickets waiting for you come first, then blocked reviews, then building, then ready, by key within a stage"
