from types import SimpleNamespace

from magi.domain.snoozes import asleep, awake, change_marks

PR = "https://github.com/acme/app/pull/1"
OTHER = "https://github.com/acme/app/pull/2"
TICKET = "https://acme.atlassian.net/browse/ACME-1"
NEW = {"at": "2026-10-24T02:04", "label": "New PR", "item": PR, "group": PR}
PUSHED = {**NEW, "at": "2026-10-24T09:00", "label": "New commits"}
APPROVED = {**NEW, "at": "2026-10-25T03:00", "label": "Approved"}
MOVED = {"at": "2026-10-25T04:00", "label": "Done", "item": TICKET, "group": PR}


def test_change_marks():
    assert change_marks([APPROVED, NEW])[PR] == "2026-10-25T03:00 Approved", "an item is marked by its newest change, as it happened"
    assert change_marks([MOVED, NEW]) == {TICKET: "2026-10-25T04:00 Done", PR: "2026-10-25T04:00 Done"}, \
        "a ticket's move marks the ticket and the pr whose group it joins"


def test_a_snooze_lasts_until_the_item_changes():
    snoozed = {PR: "2026-10-24T02:04 New PR"}
    assert asleep(snoozed, [NEW], {PR}) == snoozed, "an item with no change since its snooze stays hidden"
    assert asleep(snoozed, [], {PR}) == snoozed, "a change that left the 24 hour window does not wake the item"
    assert asleep(snoozed, [APPROVED, NEW], {PR}) == {}, "a change newer than the snooze wakes the item"
    assert asleep(snoozed, [MOVED, NEW], {PR}) == {}, "a move of the pr's ticket wakes the pr"
    assert asleep(snoozed, [NEW], set()) == {}, "an item that left its box drops its snooze"
    assert asleep({PR: None}, [], {PR}) == {PR: None}, "an item snoozed with no change stays hidden until one comes"
    assert asleep({PR: None}, [NEW], {PR}) == {}, "an item snoozed with no change wakes on its first one"


def test_the_window_moving_on_wakes_nothing():
    mark = change_marks([PUSHED, NEW])[PR]
    assert asleep({PR: mark}, [PUSHED], {PR}) == {PR: mark}, "the new pr change leaving the window is no new change"


def test_awake():
    items = [SimpleNamespace(url=PR), SimpleNamespace(url=OTHER), SimpleNamespace(url=PR)]
    assert awake(items, {PR: "2026-10-24T02:04 New PR"}, [NEW]) == [items[1]], \
        "every item of a snoozed url stays out until it changes"
    assert awake(items, {PR: "2026-10-24T02:04 New PR"}, [APPROVED, NEW]) == items, "a changed item is back"
