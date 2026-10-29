"""The factory box: the factory's tickets read from its stage files and herdr, without Jira or GitHub."""

from ..domain.factory import factory_tickets


class Factory:
    def __init__(self, source):
        self.source = source

    def collect(self):
        return factory_tickets(self.source.stages(), self.source.agents())
