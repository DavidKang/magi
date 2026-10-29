"""What on the board is mine: the PRs I opened and the ones asking for my review, the changes on them and on my tickets, the epics holding my tickets."""


def authored(prs, me):
    return [pr for pr in prs if pr.author["login"] == me]


def my_prs(mine, asked):
    """The PRs I opened and the ones asking for my review, each once."""
    found = {pr.url for pr in mine}
    return mine + [pr for pr in asked if pr.url not in found]


def my_changes(changes, prs, keys, browse):
    """Every change of a group holding one on my PRs or my tickets, so its row reads as it does for the team."""
    mine = {pr.url for pr in prs} | {browse + key for key in keys}
    groups = {c["group"] for c in changes if c["item"] in mine or c["group"] in mine}
    return [c for c in changes if c["group"] in groups]


def my_epics(epics, tickets_by_epic, keys):
    """The epics holding one of my tickets."""
    return [epic for epic in epics if any(ticket.key in keys for ticket in tickets_by_epic[epic.key])]
