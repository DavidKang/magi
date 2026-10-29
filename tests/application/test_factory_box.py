import datetime as dt

from magi.application.factory import Factory
from magi.domain.factory import Agent, Stage


class FakeFactory:
    """The stage files and herdr's agents, in the shapes the real adapter returns."""

    def __init__(self, stages, agents):
        self.found = stages, agents

    def stages(self):
        return self.found[0]

    def agents(self):
        return self.found[1]


def test_the_factory_lists_each_ticket_beside_its_session():
    at = dt.datetime(2026, 10, 29, 9, 0, tzinfo=dt.timezone.utc)
    source = FakeFactory([Stage("ACME-1", "ready", "", at), Stage("ACME-2", "waiting-you", "which repo?", at)], [Agent("ACME-1", "done")])
    found = Factory(source).collect()
    assert [(ticket.key, ticket.stage, ticket.agent) for ticket in found] == [("ACME-2", "waiting-you", None), ("ACME-1", "ready", "done")], \
        "the factory reads the stage files and herdr's agents and lists each ticket with its session, the ones needing you first"
