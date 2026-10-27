import datetime as dt
from dataclasses import replace

import pytest

from builders import EPIC, PR_ONE, PR_TWO, STATED
from magi.domain import changes, keys
from magi.domain.entities import Ticket


def test_epic_changes():
    epic_one, epic_two = EPIC, replace(EPIC, key="ACME-200", summary="Epic two")
    one, two, three = (Ticket(key=key, summary=f"Ticket {key}", status="En proceso") for key in ("ACME-1", "ACME-2", "ACME-3"))
    summaries = {t.key: t.summary for t in (one, two, three)}
    pr = replace(PR_TWO, head_ref_oid="abc")
    before = changes.snapshot([epic_one], {"ACME-100": [one]}, [], STATED)
    now = changes.snapshot([epic_one, epic_two], {"ACME-100": [one], "ACME-200": [two, three]}, [pr], STATED)
    found = changes.changes_between(before, now, summaries, {}, STATED)
    assert ([(c["label"], c["item"]) for c in found]
            == [("New epic", "https://acme.atlassian.net/browse/ACME-200")]), "a new epic is one change with its summary"
    assert found[0]["subject"]["title"] == "Epic two", "a new epic is one change with its summary"
    assert changes.vanished_prs(now, before) == [], "an epic leaving needs no lookup of its PRs"
    found = changes.changes_between(now, before, summaries, {}, STATED)
    assert [(c["label"], c["item"]) for c in found] == [("Off the epics", "https://acme.atlassian.net/browse/ACME-200")], \
        "an epic leaving is one change, without per-ticket changes"
    grown = changes.snapshot([epic_one], {"ACME-100": [one, two]}, [], STATED)
    found = changes.changes_between(before, grown, summaries, {}, STATED)
    assert [c["label"] for c in found] == ["In Progress"], "a new ticket in a known epic is a change, its status in English"
    assert found[0]["note"] == "joins ACME-100 Epic one", "a new ticket names the epic it joins"
    legacy = {key: value for key, value in before.items() if key != "epics"}
    found = changes.changes_between(legacy, grown, summaries, {}, STATED)
    assert [c["label"] for c in found] == ["In Progress"], "a saved state without epics still reports new tickets"


def test_domain_returns_data():
    gone = replace(PR_ONE, url="https://github.com/acme/app/pull/8", number=8, title="[ACME-1] Gone", head_ref_oid="x")
    before = changes.snapshot([], {}, [gone], STATED)
    now = changes.snapshot([], {}, [], STATED)
    assert changes.vanished_prs(before, now) == [gone.url], "a vanished pr outside quiet epics needs its state"
    found = changes.changes_between(before, now, {}, {gone.url: "MERGED"}, STATED)
    assert (found == [
          {"item": gone.url, "group": gone.url, "tone": "approved", "label": "Merged", "note": None, "aside": None, "told": False,
           "subject": {"kind": "pr", "url": gone.url, "ref": "app#8", "title": "[ACME-1] Gone"}}]), \
        "a vanished pr is labelled from the state it was given, as data"


def test_pr_titles_read_like_their_links():
    for title, shown in (("[ACME-1]NoSpace", "[ACME-1] NoSpace"), ("[ACME-6]   multi   space", "[ACME-6] multi   space"),
                         ("[ACME-1][ACME-30] mixed", "[ACME-1] [ACME-30] mixed"), ("[ACME-4] ", "[ACME-4]"), ("No key", "No key")):
        assert changes.subject_text(changes.pr_subject("u", "app#1", title)) == shown, f"a pr titled {title!r} reads {shown!r}"


def test_a_new_ticket_names_its_own_epic():
    epic_two = replace(EPIC, key="ACME-200", summary="Epic two")
    one, two = (Ticket(key=key, summary=f"Ticket {key}", status="En proceso") for key in ("ACME-1", "ACME-2"))
    before = changes.snapshot([EPIC, epic_two], {EPIC.key: [], epic_two.key: []}, [], STATED)
    now = changes.snapshot([EPIC, epic_two], {EPIC.key: [one], epic_two.key: [two]}, [], STATED)
    found = changes.changes_between(before, now, {"ACME-1": "Ticket one", "ACME-2": "Ticket two"}, {}, STATED)
    assert [(c["subject"]["ref"], c["note"]) for c in found] == [("ACME-1", "joins ACME-100 Epic one"), ("ACME-2", "joins ACME-200 Epic two")], \
        "each new ticket names the epic it joins, not another epic on the board"


def test_a_snapshot_names_its_epics():
    taken = changes.snapshot([EPIC], {EPIC.key: []}, [], STATED)
    assert changes.snapshot_epics(taken) == [EPIC.key], "a snapshot names the epics it was taken with"


def test_vanished_prs_need_their_state():
    gone = replace(PR_ONE, head_ref_oid="x")
    with pytest.raises(KeyError):
        changes.changes_between(changes.snapshot([], {}, [gone], STATED), changes.snapshot([], {}, [], STATED), {}, {}, STATED)


def test_domain_takes_the_settings_it_is_given():
    pr = replace(PR_ONE, head_ref_oid="a1")
    found = changes.changes_between(changes.snapshot([], {}, [], STATED), changes.snapshot([], {}, [pr], STATED), {}, {}, STATED)
    assert [c["label"] for c in found] == ["New PR"], "changes take the settings they are given"
    assert keys.ticket_keys_in(pr, "ACME") == {"ACME-1"}, "pr ticket keys take the project they are given"


def test_a_ticket_change_joins_the_only_pr_that_names_it():
    pr = replace(PR_ONE, head_ref_oid="a1")
    one = Ticket(key="ACME-1", summary="Ticket one", status="En proceso")
    moved = replace(one, status="En revisión")
    before = changes.snapshot([EPIC], {"ACME-100": [one]}, [pr], STATED)
    now = changes.snapshot([EPIC], {"ACME-100": [moved]}, [pr], STATED)
    found = changes.changes_between(before, now, {"ACME-1": "Ticket one"}, {}, STATED)
    assert [(c["label"], c["group"]) for c in found] == [("In review", PR_ONE.url)], "a ticket change joins the group of the one pr that names it"
    assert found[0]["aside"] == "was: In Progress", "a ticket change names both statuses in English"
    other = replace(PR_TWO, title="[ACME-1] Also", head_ref_name="also", head_ref_oid="b1")
    twice = changes.snapshot([EPIC], {"ACME-100": [moved]}, [pr, other], STATED)
    found = changes.changes_between(before, twice, {"ACME-1": "Ticket one"}, {}, STATED)
    assert [c["group"] for c in found if c["label"] == "In review"] == ["https://acme.atlassian.net/browse/ACME-1"], \
        "a ticket two prs name keeps a group of its own"
    empty = changes.snapshot([EPIC], {"ACME-100": []}, [pr], STATED)
    joined = changes.changes_between(empty, now, {"ACME-1": "Ticket one"}, {}, STATED)
    left = changes.changes_between(now, empty, {}, {}, STATED)
    assert [(c["note"], c["group"]) for c in joined + left] == [("joins ACME-100 Epic one", PR_ONE.url), ("(cancelled or moved)", PR_ONE.url)], \
        "a ticket joining or leaving the epics joins the group of its pr too"


def test_a_ticket_leaving_the_epics_keeps_its_title():
    one = Ticket(key="ACME-1", summary="Ticket one", status="En proceso")
    before = changes.snapshot([EPIC], {EPIC.key: [one]}, [], STATED)
    now = changes.snapshot([EPIC], {EPIC.key: []}, [], STATED)
    found = changes.changes_between(before, now, {}, {}, STATED)
    assert [changes.change_text(c) for c in found] == ["ACME-1 Ticket one (cancelled or moved)"], \
        "a ticket leaving the epics keeps the title it had on the board"
    untitled = {**before, "tickets": {"ACME-1": {"status": "En proceso", "summary": None}}}
    found = changes.changes_between(untitled, now, {}, {}, STATED)
    assert [changes.change_text(c) for c in found] == ["ACME-1 (cancelled or moved)"], \
        "a ticket leaving the epics before its title was ever saved shows its key alone"


def test_a_pr_change_leads_its_ticket_move_from_the_same_refresh():
    pr = replace(PR_ONE, head_ref_oid="a1")
    before = changes.snapshot([EPIC], {"ACME-100": [Ticket(key="ACME-1", summary="Ticket one", status="En revisión")]}, [pr], STATED)
    now = changes.snapshot([EPIC], {"ACME-100": [Ticket(key="ACME-1", summary="Ticket one", status="Finalizado")]}, [], STATED)
    found = changes.recent_changes({"snapshot": before, "changes": []}, now, {"ACME-1": "Ticket one"}, dt.datetime(2026, 10, 25, 9, 0),
                                   {PR_ONE.url: "MERGED"}, STATED)
    assert [c["label"] for c in changes.latest(found, "group")] == ["Merged"], "a pr's own change leads its ticket's move from the same refresh"


def test_recent_changes_keep_every_change_of_the_last_day():
    subject = changes.pr_subject(PR_ONE.url, "app#1", PR_ONE.title)
    earlier = {"at": "2026-10-25T08:00", **changes.change(subject, "waiting", changes.PUSHED)}
    stale = {**earlier, "at": "2026-10-24T08:00"}
    before = changes.snapshot([], {}, [replace(PR_ONE, head_ref_oid="a1")], STATED)
    now = changes.snapshot([], {}, [replace(PR_ONE, head_ref_oid="a2")], STATED)
    found = changes.recent_changes({"snapshot": before, "changes": [earlier, stale]}, now, {}, dt.datetime(2026, 10, 25, 9, 0), {}, STATED)
    assert [c["at"] for c in found] == ["2026-10-25T09:00", "2026-10-25T08:00"], "every change of the last 24 h stays, newest first"


def test_latest_keeps_one_change_per_item_or_group():
    ticket = {"at": "2026-10-25T09:00", "item": "ticket", "group": "pr", "label": "En revisión"}
    pushed = {"at": "2026-10-25T08:00", "item": "pr", "group": "pr", "label": changes.PUSHED}
    opened = {"at": "2026-10-25T07:00", "item": "pr", "group": "pr", "label": changes.NEW_PR}
    assert changes.latest([ticket, pushed, opened], "group") == [ticket], "a group shows only its latest change"
    assert changes.latest([ticket, pushed, opened], "item") == [ticket, {**opened, "at": "2026-10-25T08:00"}], \
        "a pr new in the window stays a new pr, at the time of its latest change"
    assert changes.latest([ticket, opened], "group") == [ticket], "a ticket move after its pr opened leads the pr's row"


def test_group_changes_leave_out_what_the_pr_history_tells():
    found = [{"item": "ticket", "group": "pr", "label": "In review", "told": False}, {"item": "pr", "group": "pr", "label": changes.PUSHED, "told": True},
             {"item": "pr", "group": "pr", "label": "Approved", "told": True}, {"item": "pr", "group": "pr", "label": "Commented", "told": False},
             {"item": "pr", "group": "pr", "label": "Merged", "told": False}, {"item": "other", "group": "other", "label": "New epic", "told": False}]
    assert [c["label"] for c in changes.group_changes(found, "pr", {"pr": []})] == ["In review", "Commented", "Merged"], \
        "a pr's own history tells the changes its commits and reviews caused, and no other"
    assert [c["label"] for c in changes.group_changes(found, "pr", {})] == ["In review", changes.PUSHED, "Approved", "Commented", "Merged"], \
        "without a history every change of the group is told"


def test_a_pr_change_is_told_by_its_history_only_when_a_commit_or_review_caused_it():
    reviewed = {"state": "COMMENTED", "author": {"login": "bob"}, "submittedAt": "2026-10-22T10:00:00Z"}
    draft = replace(PR_ONE, is_draft=True, reviews=[reviewed], head_ref_oid="a1")
    ready = replace(draft, is_draft=False)
    approved = replace(ready, reviews=[reviewed, {**reviewed, "state": "APPROVED"}])
    for before, now, expected in ((draft, ready, [("Commented", False)]), (ready, approved, [("Approved", True)]),
                                  (ready, replace(ready, head_ref_oid="a2", commits=[*ready.commits, {"committedDate": "2026-10-23T10:00:00Z"}]),
                                   [(changes.PUSHED, True)]),
                                  (ready, replace(ready, head_ref_oid="a0", commits=[{"committedDate": "2026-10-20T10:00:00Z"}]), [(changes.PUSHED, False)])):
        found = changes.changes_between(changes.snapshot([], {}, [before], STATED), changes.snapshot([], {}, [now], STATED), {}, {}, STATED)
        assert [(c["label"], c["told"]) for c in found] == expected, "only a newer commit or a new review makes a pr change one its history tells"


def test_a_push_on_a_snapshot_without_its_commit_time_is_told():
    before = changes.snapshot([], {}, [PR_ONE], STATED)
    del before["prs"][PR_ONE.url]["pushed"]
    found = changes.changes_between(before, changes.snapshot([], {}, [replace(PR_ONE, head_ref_oid="a2")], STATED), {}, {}, STATED)
    assert [(c["label"], c["told"]) for c in found] == [(changes.PUSHED, True)], "a snapshot saved before commit times were kept tells a push as before"


def test_a_pending_review_is_no_new_review():
    submitted = {"state": "COMMENTED", "author": {"login": "bob"}, "submittedAt": "2026-10-22T10:00:00Z"}
    before = replace(PR_ONE, reviews=[submitted])
    now = replace(before, reviews=[submitted, {"state": "PENDING", "author": {"login": "carol"}, "submittedAt": None}])
    found = changes.changes_between(changes.snapshot([], {}, [before], STATED), changes.snapshot([], {}, [now], STATED), {}, {}, STATED)
    assert found == [], "a review not submitted yet changes nothing on the board"


def test_a_ticket_joins_the_group_of_its_newest_change():
    one = Ticket(key="ACME-1", summary="Ticket one", status="En proceso")
    moved = replace(one, status="En revisión")
    alone = {"at": "2026-10-25T07:00", **changes.change(changes.ticket_subject("ACME-1", STATED.jira_browse, "Ticket one"), "waiting", "In progress")}
    before = changes.snapshot([EPIC], {EPIC.key: [one]}, [PR_ONE], STATED)
    now = changes.snapshot([EPIC], {EPIC.key: [moved]}, [PR_ONE], STATED)
    found = changes.recent_changes({"snapshot": before, "changes": [alone]}, now, {"ACME-1": "Ticket one"}, dt.datetime(2026, 10, 25, 9, 0), {}, STATED)
    assert [(c["label"], c["group"]) for c in found] == [("In review", PR_ONE.url), ("In progress", PR_ONE.url)], \
        "a ticket's earlier changes join the pr its newest change joined"
    assert [c["label"] for c in changes.latest(found, "group")] == ["In review"], "a ticket shows once, at its newest status"
