"""Jira statuses: the board column each one falls in, and how it reads."""

COLUMNS = [
    ("todo", "To do", {"Backlog", "Tareas por hacer"}),
    ("doing", "In progress", {"En proceso", "Developing", "Paused"}),
    ("review", "In review", {"En revisión"}),
    ("deploy", "Deploy", {"Ready To Deploy", "Rollout"}),
    ("done", "Done", {"Finalizado"}),
]
DISCARDED = {"Rejected / Cancelled"}
STATUS_RANK = {status: i for i, (_, _, statuses) in enumerate(COLUMNS) for status in statuses}
STATUS_COLUMNS = {status: key for key, _, statuses in COLUMNS for status in statuses}
STATUS_LABELS = {"Tareas por hacer": "Todo", "En proceso": "In Progress", "En revisión": "In review", "Finalizado": "Done"}
EPIC_STATUSES = ["Developing", "Rollout"]
ACTIVE_COLUMNS = {"doing", "review", "deploy"}
KANBAN_COLUMNS = ["review", "doing", "deploy", "todo"]
KANBAN_RANK = {status: KANBAN_COLUMNS.index(key) for key, _, statuses in COLUMNS if key in KANBAN_COLUMNS for status in statuses}


class UnmappedStatus(Exception):
    pass


def column_for(status):
    for key, _, statuses in COLUMNS:
        if status in statuses:
            return key
    if status in DISCARDED:
        return None
    raise UnmappedStatus(f"Unmapped Jira status: {status}")


def status_label(status):
    return STATUS_LABELS.get(status, status)


def ticket_order(ticket):
    return STATUS_RANK.get(ticket.status, len(COLUMNS)), ticket.status


def kanban_order(ticket):
    """The kanban box's order: its columns as KANBAN_COLUMNS lists them, each status together, and any other status last;
    a stable sort keeps Jira's rank within one."""
    return KANBAN_RANK.get(ticket.status, len(KANBAN_COLUMNS)), ticket.status
