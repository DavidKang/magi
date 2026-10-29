"""The factory box: the factory's tickets read from its stage files and herdr, without Jira or GitHub."""

from dataclasses import replace

from ..domain.factory import factory_tickets


class Factory:
    def __init__(self, source):
        self.source = source

    def collect(self):
        tickets = factory_tickets(self.source.stages(), self.source.agents())
        return [replace(ticket, output=tuple(self.source.output(ticket.pane))) if ticket.pane else ticket for ticket in tickets]

    def focus(self, pane):
        self.source.focus(pane)
