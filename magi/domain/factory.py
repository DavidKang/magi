"""The software factory's tickets: each one's stage beside the herdr session working on it."""

import datetime as dt
from dataclasses import dataclass

# The stages the factory writes, the ones needing you first.
STAGES = ("waiting-you", "review-blocked", "building", "ready")


@dataclass(frozen=True)
class Stage:
    key: str
    stage: str
    detail: str
    since: dt.datetime | None


@dataclass(frozen=True)
class Agent:
    folder: str
    status: str | None
    pane: str | None = None


@dataclass(frozen=True)
class FactoryTicket:
    key: str
    stage: str
    detail: str
    since: dt.datetime | None
    agent: str | None
    pane: str | None = None
    # What the agent last wrote in its terminal, line by line.
    output: tuple = ()


def session_of(key, agents):
    """The herdr agent working in the ticket's worktree, named after its key alone or with a slug; None without one."""
    for agent in agents:
        if agent.folder == key or agent.folder.startswith(f"{key}-"):
            return agent
    return None


def factory_tickets(stages, agents):
    found = []
    for stage in stages:
        if stage.stage in STAGES:
            agent = session_of(stage.key, agents)
            found.append(FactoryTicket(stage.key, stage.stage, stage.detail, stage.since, agent and agent.status, agent and agent.pane))
    return sorted(found, key=lambda ticket: (STAGES.index(ticket.stage), ticket.key))
