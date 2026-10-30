"""The board's boxes: their names, empty lines, column widths, the digits that reach them in the TUI and their numbers on the web page."""

from ..domain import changes
from . import frames, theme

# The title takes the room the other columns leave, up to MAX_TITLE; the rest goes to the repo, so it sits at the right edge.
PR_WIDTHS = [None, 10, 32, 4, 18]
# LCARS draws review, CI, conflict and days as padded pills, which need more room than their plain text.
LCARS_PR_WIDTHS = [None, 10, 36, 8, 18]
# A ticket's row shows its oldest PR's label as the PR's row does, so it takes the same room.
KANBAN_WIDTHS = [10, 11, 16, 32, 4, None]
FRAMED_WIDTHS = {"prs": LCARS_PR_WIDTHS, "kanban": [10, 11, 16, 36, 4, None]}
MIN_TITLE, MAX_TITLE = 20, 60
# A box too narrow for MIN_TITLE still shows this much of the title.
NARROW_TITLE = 10
TURN_COLUMNS = {"prs": 2, "kanban": 3}
CHANGE_WIDTHS = [12, 18, 14, None]
NO_CHANGES = f"no changes in the last {changes.CHANGES_HOURS} h"
# The web page's boxes and their numbers: magi web keeps my prs and my tickets, and numbers them as the TUI once did.
SECTIONS = {"kanban": ("jira tickets", "no tickets on the board", KANBAN_WIDTHS),
            "prs": ("team prs", "no open prs", PR_WIDTHS),
            "changes": ("changes", NO_CHANGES, CHANGE_WIDTHS),
            "epics": ("epics", "no epics", [9, 20, 6, None]),
            "mine_prs": ("my prs", "no open prs", PR_WIDTHS),
            "mine_tickets": ("my tickets", "no open tickets", [10, None])}
NUMBERS = {key: n for n, key in enumerate(SECTIONS, 3)}
# The TUI's boxes, in digit order. The factory's is the TUI's alone: magi web never reads the factory's stage files or herdr.
BOXES = {**{key: SECTIONS[key] for key in ("kanban", "prs", "changes", "epics")},
         "factory": ("factory", "no factory tickets", [10, 18, 4, 8, None])}
DIGITS = {key: n for n, key in enumerate(BOXES, 1)}
MAIN = ["kanban", "prs", "changes"]
# The boxes under the details.
ASIDE = ["factory", "epics"]


def widths(key, room=None, rows=()):
    found = list(FRAMED_WIDTHS.get(key, BOXES[key][2]) if theme.frame() else BOXES[key][2])
    if key in TURN_COLUMNS and rows:
        column = TURN_COLUMNS[key]
        # Framed themes draw the label as a pill, four cells wider than its text.
        found[column] = min(found[column], max(len(row.cells[column][0]) for row in rows) + 4 * bool(theme.frame()))
    if None not in found[:-1]:
        return found
    if not room:
        return [MIN_TITLE if width is None else width for width in found]
    left = room - sum(filter(None, found)) - len(found)
    title = min(max(left, NARROW_TITLE), MAX_TITLE)
    return [title, *found[1:-1], max(found[-1] + left - title, 0)]


def section_name(key):
    default = BOXES[key][0] if key in BOXES else key
    return frames.box_name(theme.current, key, default)


def panel_title(key, count):
    number, name = DIGITS[key], section_name(key)
    title = f"{number:02d}-{name.upper()}" if theme.frame() else f"[{number}] {name}"
    return title if count is None else f"{title} {count}"

