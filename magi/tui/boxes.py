"""The board's boxes: their names, empty lines, column widths, the tabs they sit in and the digits that reach them."""

from ..domain import changes
from . import frames, theme

# The title takes the room the other columns leave, up to MAX_TITLE; the rest goes to the repo, so it sits at the right edge.
PR_WIDTHS = [None, 10, 27, 4, 18]
# LCARS draws review, CI, conflict and days as padded pills, which need more room than their plain text.
LCARS_PR_WIDTHS = [None, 10, 31, 8, 18]
MIN_TITLE, MAX_TITLE = 20, 60
# A box too narrow for MIN_TITLE still shows this much of the title.
NARROW_TITLE = 10
CHANGE_WIDTHS = [12, 18, 14, None]
NO_CHANGES = f"no changes in the last {changes.CHANGES_HOURS} h"
# The board's boxes: magi web draws these too.
SECTIONS = {"kanban": ("kanban", "no tickets on the board", [10, 11, 16, 22, 4, None]),
            "prs": ("team prs", "no open prs", PR_WIDTHS),
            "changes": ("changes", NO_CHANGES, CHANGE_WIDTHS),
            "epics": ("epics", "no epics", [9, 20, 6, None]),
            "mine_prs": ("my prs", "no open prs", PR_WIDTHS),
            "mine_tickets": ("my tickets", "no open tickets", [10, None])}
# The factory's box is the TUI's alone: magi web never reads the factory's stage files or herdr.
BOXES = {**SECTIONS, "factory": ("factory", "no factory tickets", [10, 18, 4, 8, None])}
# The factory's box has no tab: it stays under the details on every tab.
TABS = {"overview": ["kanban", "prs", "changes", "epics"], "mine": ["mine_prs", "mine_tickets"]}
# The tabs take the first digits and the boxes the next ones.
NUMBERS = {key: n for n, key in enumerate(BOXES, len(TABS) + 1)}
TAB_NUMBERS = {tab: n for n, tab in enumerate(TABS, 1)}
TAB_OF = {key: tab for tab, keys in TABS.items() for key in keys}


def widths(key, room=None):
    found = BOXES[key][2]
    found = LCARS_PR_WIDTHS if found is PR_WIDTHS and theme.frame() else found
    if None not in found[:-1]:
        return found
    if not room:
        return [MIN_TITLE if width is None else width for width in found]
    left = room - sum(filter(None, found)) - len(found)
    title = min(max(left, NARROW_TITLE), MAX_TITLE)
    return [title, *found[1:-1], found[-1] + max(left - title, 0)]


def section_name(key):
    default = BOXES[key][0] if key in BOXES else key
    return frames.box_name(theme.current, key, default)


def panel_title(key, count):
    number, name = NUMBERS[key], section_name(key)
    title = f"{number:02d}-{name.upper()}" if theme.frame() else f"[{number}] {name}"
    return title if count is None else f"{title} {count}"

