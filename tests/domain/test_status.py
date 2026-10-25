import pytest

from builders import make_ticket
from magi.domain.status import UnmappedStatus, column_for, status_label, ticket_order


def test_status_labels():
    labels = {status: status_label(status) for status in
              ["Tareas por hacer", "En proceso", "En revisión", "Finalizado", "Backlog", "Developing", "Blocked"]}
    assert (labels == {
          "Tareas por hacer": "Todo", "En proceso": "In Progress", "En revisión": "In review", "Finalizado": "Done",
          "Backlog": "Backlog", "Developing": "Developing", "Blocked": "Blocked"}), "Spanish statuses read in English, the rest as Jira names them"


def test_unmapped_status_raises():
    with pytest.raises(UnmappedStatus, match="Unmapped Jira status: Blocked"):
        column_for("Blocked")


def test_tickets_order_by_column_then_status():
    statuses = ["Zeta", "Finalizado", "Developing", "Backlog", "En proceso", "En revisión", "Rollout", "Alpha"]
    ordered = [t.status for t in sorted((make_ticket(status=s) for s in statuses), key=ticket_order)]
    assert ordered == ["Backlog", "Developing", "En proceso", "En revisión", "Rollout", "Finalizado", "Alpha", "Zeta"], \
        "tickets follow the board columns, by name within one, and unknown statuses go last"
