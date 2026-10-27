"""What a file saved by an older storage version needs to read as the current one; a file not listed is dropped and fetched again."""

from ..domain.changes import PUSHED
from ..domain.status import status_label


def change_with_group(change):
    """A change saved before changes had groups and ticket statuses read in English: alone in its own group,
    and told by its PR's history when a push or a new review caused it."""
    found = {**change, "group": change["item"], "told": change["label"] == PUSHED or change["aside"] == "new review"}
    if change["subject"]["kind"] == "ticket":
        found["label"] = status_label(change["label"])
        if change["aside"]:
            found["aside"] = "was: " + status_label(change["aside"].removeprefix("was: "))
    return found


def state_with_groups(state):
    """A state saved before changes had groups and PR histories."""
    return {**state, "changes": [change_with_group(c) for c in state["changes"]], "histories": {}}


def state_with_ticket_summaries(state):
    """A state saved before its snapshot kept each ticket's summary: its tickets keep their statuses, without a title."""
    tickets = {key: {"status": status, "summary": None} for key, status in state["snapshot"]["tickets"].items()}
    return {**state, "snapshot": {**state["snapshot"], "tickets": tickets}}


# Per file, the step that brings it from the version it is keyed by to the next one.
UPGRADES = {"state": {3: state_with_groups, 4: state_with_ticket_summaries}}
