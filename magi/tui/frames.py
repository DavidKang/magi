"""Each framed theme's own words for the board: its boxes, its alert levels and its status line, shared by the TUI and the web page."""

from .. import rows
from ..domain.review import CONDITIONS
from .theme import FRAMES

LCARS_NAMES = {"attention": "bridge alerts", "prs": "crew reports", "changes": "captain's log", "epics": "missions", "mine_prs": "my reports",
               "mine_tickets": "away missions", "details": "sensor readings"}
NERV_NAMES = {"attention": "emergency", "prs": "sorties", "changes": "operations log", "epics": "projects", "mine_prs": "my sorties",
              "mine_tickets": "my orders", "details": "magi analysis"}
CYBERPUNK_NAMES = {"attention": "ncpd scanner", "prs": "fixer gigs", "changes": "datashards", "epics": "main jobs", "mine_prs": "my gigs",
                   "mine_tickets": "side jobs", "details": "kiroshi scan"}
FRAME_NAMES = {"lcars": LCARS_NAMES, "nerv": NERV_NAMES, "cyberpunk": CYBERPUNK_NAMES}
# Evangelion's blood types: orange for an unknown pattern, blue for an Angel.
NERV_CONDITIONS = {"green": "NORMAL", "yellow": "PATTERN ORANGE", "red": "PATTERN BLUE"}
# EVA 01 reads the level as Unit-01's sync with its pilot, and berserk when it breaks.
EVA_CONDITIONS = {"green": "SYNC STABLE", "yellow": "SYNC UNSTABLE", "red": "BERSERK"}
# Night City's wanted level: five stars send MaxTac.
CYBERPUNK_CONDITIONS = {"green": "NO HEAT", "yellow": "HEAT ★★", "red": "HEAT ★★★★★"}
THEME_CONDITIONS = {"nerv": NERV_CONDITIONS, "eva01": EVA_CONDITIONS, "cyberpunk": CYBERPUNK_CONDITIONS}
# The code on the LCARS elbow.
PANEL_CODE = "04-1701"


def box_name(name, key, default):
    return FRAME_NAMES.get(FRAMES.get(name), {}).get(key, default)


def condition_label(name, level):
    return THEME_CONDITIONS.get(name, CONDITIONS)[level]


def status(name, when, user, clock="%H:%M"):
    """The status line theme name writes for a refresh at when, its time in clock's format; LCARS dates it in stardates."""
    time = f"{when:{clock}}"
    lines = {"lcars": rows.stardate(when), "nerv": f"MAGI · MELCHIOR BALTHASAR CASPER · SYNC {time}", "cyberpunk": f"NIGHT CITY · NET UPLINK {time}"}
    pilot = f"EVA-01 · PILOT {user.upper()} · SYNC {time}"
    return pilot if name == "eva01" else lines.get(FRAMES.get(name), f"updated {time}")
