import datetime as dt

from magi.domain.factory import Agent, Stage, factory_tickets, session_of

UTC = dt.timezone.utc
AT = dt.datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


def stage(key, name="building", detail="", since=AT):
    return Stage(key, name, detail, since)


def test_a_ticket_finds_its_session_by_the_worktree_it_runs_in():
    agents = [Agent("radar", "idle"), Agent("KAME-12", "working"), Agent("KAME-7-find-the-dragon-balls", "done")]
    assert session_of("KAME-12", agents) == agents[1], "a ticket's session is the agent whose worktree folder is named after the key"
    assert session_of("KAME-7", agents) == agents[2], "a worktree named after the key and a slug is the ticket's session too"
    assert session_of("KAME-1", agents) is None, "KAME-1 is not KAME-12: a key matches the whole folder name or the key and a dash"


def test_two_agents_in_one_worktree_give_the_first_listed():
    agents = [Agent("KAME-12", "idle"), Agent("KAME-12-kaioken", "working")]
    assert session_of("KAME-12", agents) == agents[0], "when two herdr agents work on one ticket, its session is the first herdr lists"


def test_a_ticket_knows_the_pane_of_its_session():
    [ticket] = factory_tickets([stage("KAME-3")], [Agent("KAME-3", "working", "w2H:p2")])
    assert (ticket.agent, ticket.pane) == ("working", "w2H:p2"), "a ticket carries its session's status and the herdr pane it runs in"


def test_a_ticket_without_a_session_shows_it_absent():
    found = factory_tickets([stage("KAME-3")], [Agent("KAME-4", "working")])
    assert [(ticket.key, ticket.agent, ticket.pane) for ticket in found] == [("KAME-3", None, None)], "a ticket no herdr agent works on has no session"


def test_a_ticket_carries_its_stage_detail_and_when_it_changed():
    [ticket] = factory_tickets([stage("KAME-5", "waiting-you", "which dragon ball?")], [])
    assert (ticket.stage, ticket.detail, ticket.since) == ("waiting-you", "which dragon ball?", AT), \
        "each factory ticket reads its stage, its detail and when its stage changed"


def test_stages_the_factory_never_writes_are_left_out():
    found = factory_tickets([stage("KAME-1"), stage("KAME-3", "shipped")], [])
    assert [ticket.key for ticket in found] == ["KAME-1"], "a stage the factory never writes is not a factory ticket"


def test_tickets_needing_you_come_first():
    found = factory_tickets([stage("KAME-1", "ready"), stage("KAME-2", "building"), stage("KAME-3", "review-blocked"), stage("KAME-4", "waiting-you"),
                             stage("KAME-0", "building")], [])
    assert [ticket.key for ticket in found] == ["KAME-4", "KAME-3", "KAME-0", "KAME-2", "KAME-1"], \
        "tickets waiting for you come first, then blocked reviews, then building, then ready, by key within a stage"
