import datetime as dt

from magi.application.factory import Factory
from magi.domain.factory import Agent, Stage


class FakeFactory:
    """The stage files and herdr's agents, in the shapes the real adapter returns."""

    def __init__(self, stages, agents, outputs=None):
        self.found, self.outputs, self.focused = (stages, agents), outputs or {}, []

    def stages(self):
        return self.found[0]

    def agents(self):
        return self.found[1]

    def output(self, pane):
        return self.outputs.get(pane, [])

    def focus(self, pane):
        self.focused.append(pane)


def test_the_factory_lists_each_ticket_beside_its_session():
    at = dt.datetime(2026, 10, 29, 9, 0, tzinfo=dt.timezone.utc)
    source = FakeFactory([Stage("ACME-1", "ready", "", at), Stage("ACME-2", "waiting-you", "which repo?", at)], [Agent("ACME-1", "done")])
    found = Factory(source).collect()
    assert [(ticket.key, ticket.stage, ticket.agent) for ticket in found] == [("ACME-2", "waiting-you", None), ("ACME-1", "ready", "done")], \
        "the factory reads the stage files and herdr's agents and lists each ticket with its session, the ones needing you first"


def test_a_ticket_with_a_session_carries_what_its_agent_last_wrote():
    at = dt.datetime(2026, 10, 29, 9, 0, tzinfo=dt.timezone.utc)
    source = FakeFactory([Stage("ACME-1", "waiting-you", "", at), Stage("ACME-2", "building", "", at)], [Agent("ACME-1", "blocked", "w1:p1")],
                         {"w1:p1": ["Which repo?"]})
    found = Factory(source).collect()
    assert [(ticket.key, ticket.output) for ticket in found] == [("ACME-1", ("Which repo?",)), ("ACME-2", ())], \
        "each ticket with a herdr session carries what its agent last wrote, and one without has nothing"


def test_focus_jumps_to_the_pane():
    source = FakeFactory([], [])
    Factory(source).focus("w1:p1")
    assert source.focused == ["w1:p1"], "the factory jumps to the herdr pane it is given"
