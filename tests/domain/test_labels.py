from builders import make_ticket, make_ticket_detail
from magi.domain.labels import blocked


def test_a_ticket_is_blocked_by_its_blocked_label():
    assert blocked(make_ticket(detail=make_ticket_detail(labels=["backend", "blocked"]))), "a ticket labelled blocked is blocked"
    assert not blocked(make_ticket(detail=make_ticket_detail(labels=["backend"]))), "a ticket without the blocked label is not"
