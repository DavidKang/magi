"""The board's entities, built by the github and jira adapters. Nested records (reviews, threads, comments, links) stay plain dicts."""

from dataclasses import dataclass, field


@dataclass
class Epic:
    key: str
    summary: str
    status: str
    owner: str


@dataclass
class TicketDetail:
    type: str
    priority: str | None
    labels: list
    creator: str
    created: str
    updated: str
    epic: dict | None
    links: list
    description: str
    comments: list


@dataclass
class PullRequest:
    number: int
    title: str
    url: str
    updated_at: str
    head_ref_name: str
    head_ref_oid: str
    is_draft: bool
    created_at: str
    review_decision: str | None
    mergeable: str
    author: dict
    review_requests: list
    reviews: list
    commits: list
    threads: list
    conversation: list
    repo: str
    ci: str
    failed_checks: list
    conflicts: list


@dataclass
class Ticket:
    key: str
    summary: str
    status: str
    column: str | None = None
    assignee: str | None = None
    updated: str | None = None
    prs: list = field(default_factory=list)
    detail: TicketDetail | None = None


@dataclass
class FoundPr:
    """A PR as a search finds it: enough to pick the PRs to show and to tell whether their details changed."""
    url: str
    number: int
    updated_at: str
    title: str
    head_ref_name: str
    base_ref_name: str
    head_ref_oid: str
    mergeable: str
    author: dict
    name_with_owner: str
    repo: str
    ci: str


def ticket_from(data):
    """A ticket read back from json, with its PRs and detail."""
    return Ticket(**{**data, "prs": [PullRequest(**pr) for pr in data["prs"]],
                     "detail": TicketDetail(**data["detail"]) if data["detail"] else None})
