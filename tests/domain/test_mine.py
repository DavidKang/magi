from builders import make_epic, make_pr, make_ticket
from magi.domain.mine import authored, my_changes, my_epics, my_prs

BROWSE = "https://acme.atlassian.net/browse/"
MINE = make_pr(url="https://github.com/acme/app/pull/1", author={"login": "alice"})
THEIRS = make_pr(url="https://github.com/acme/app/pull/2", author={"login": "bob"})
ASKED = make_pr(url="https://github.com/acme/app/pull/3", author={"login": "carol"})


def test_authored_prs_are_the_ones_i_opened():
    assert authored([MINE, THEIRS], "alice") == [MINE], "the prs I authored are the ones whose author is me"


def test_my_prs_are_mine_and_the_ones_asking_for_my_review():
    assert [pr.url for pr in my_prs([MINE], [ASKED])] == [MINE.url, ASKED.url], "my prs are the ones I opened and the ones asking for my review"
    assert [pr.url for pr in my_prs([MINE], [MINE])] == [MINE.url], "a pr of mine asking for my review shows once"


def test_my_changes_are_the_groups_touching_my_prs_and_tickets():
    on_pr = {"item": MINE.url, "group": MINE.url}
    on_ticket = {"item": BROWSE + "ACME-1", "group": THEIRS.url}
    theirs_in_my_group = {"item": THEIRS.url, "group": THEIRS.url}
    other = {"item": ASKED.url, "group": ASKED.url}
    assert my_changes([on_pr, on_ticket, theirs_in_my_group, other], [MINE], {"ACME-1"}, BROWSE) == [on_pr, on_ticket, theirs_in_my_group], \
        "my changes are every change of a group that holds one on my prs or tickets, so a row reads as it does for the team"
    assert my_changes([other], [], set(), BROWSE) == [], "with nothing of mine, no change is mine"


def test_my_epics_hold_my_tickets():
    epics = [make_epic(key="ACME-100"), make_epic(key="ACME-200")]
    tickets = {"ACME-100": [make_ticket(key="ACME-1")], "ACME-200": [make_ticket(key="ACME-2")]}
    assert [e.key for e in my_epics(epics, tickets, {"ACME-1"})] == ["ACME-100"], "my epics are the ones holding one of my tickets"
    assert my_epics(epics, tickets, set()) == [], "with no tickets of mine, no epic is mine"
