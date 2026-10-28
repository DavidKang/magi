"""Snoozed items: kept off their box until Magi sees a change on them newer than the one they had when snoozed."""

from .changes import change_mark


def change_marks(changes):
    """The newest change on each item, as the mark a snooze keeps; a ticket's change also marks the PR whose group it joins.

    changes come newest first, so a change leaving the 24 hour window takes every older one with it and never changes a mark.
    """
    marks = {}
    for c in changes:
        for key in (c["item"], c["group"]):
            marks.setdefault(key, change_mark(c))
    return marks


def asleep(snoozed, changes, shown):
    """The snoozes that still hide their item: snoozed maps a url to its mark when snoozed, and an item off its box or changed since wakes up."""
    marks = change_marks(changes)
    return {url: mark for url, mark in snoozed.items() if url in shown and marks.get(url, mark) == mark}


def awake(items, snoozed, changes):
    """The items no snooze hides, each kept under its url."""
    hidden = asleep(snoozed, changes, {item.url for item in items})
    return [item for item in items if item.url not in hidden]
