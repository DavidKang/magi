from dataclasses import replace

import pytest

from builders import EPIC, PR_ONE, PR_TWO, STATED
from tarkon.domain import changes, keys
from tarkon.domain.entities import Ticket


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
    assert [c["label"] for c in found] == ["En proceso"], "a new ticket in a known epic still joins the epics"
    assert found[0]["note"] == "joins the epics", "a new ticket in a known epic still joins the epics"
    legacy = {key: value for key, value in before.items() if key != "epics"}
    found = changes.changes_between(legacy, grown, summaries, {}, STATED)
    assert [c["label"] for c in found] == ["En proceso"], "a saved state without epics still reports new tickets"


def test_domain_returns_data():
    gone = replace(PR_ONE, url="https://github.com/acme/app/pull/8", number=8, title="[ACME-1] Gone", head_ref_oid="x")
    before = changes.snapshot([], {}, [gone], STATED)
    now = changes.snapshot([], {}, [], STATED)
    assert changes.vanished_prs(before, now) == [gone.url], "a vanished pr outside quiet epics needs its state"
    found = changes.changes_between(before, now, {}, {gone.url: "MERGED"}, STATED)
    assert (found == [
          {"item": gone.url, "tone": "approved", "label": "Merged", "note": None, "aside": None,
           "subject": {"kind": "pr", "url": gone.url, "ref": "app#8", "title": "[ACME-1] Gone"}}]), \
        "a vanished pr is labelled from the state it was given, as data"


def test_pr_titles_read_like_their_links():
    for title, shown in (("[ACME-1]NoSpace", "[ACME-1] NoSpace"), ("[ACME-6]   multi   space", "[ACME-6] multi   space"),
                         ("[ACME-1][ACME-30] mixed", "[ACME-1] [ACME-30] mixed"), ("[ACME-4] ", "[ACME-4]"), ("No key", "No key")):
        assert changes.subject_text(changes.pr_subject("u", "app#1", title)) == shown, f"a pr titled {title!r} reads {shown!r}"


def test_vanished_prs_need_their_state():
    gone = replace(PR_ONE, head_ref_oid="x")
    with pytest.raises(KeyError):
        changes.changes_between(changes.snapshot([], {}, [gone], STATED), changes.snapshot([], {}, [], STATED), {}, {}, STATED)


def test_domain_takes_the_settings_it_is_given():
    pr = replace(PR_ONE, head_ref_oid="a1")
    found = changes.changes_between(changes.snapshot([], {}, [], STATED), changes.snapshot([], {}, [pr], STATED), {}, {}, STATED)
    assert [c["label"] for c in found] == ["New PR"], "changes take the settings they are given"
    assert keys.ticket_keys_in(pr, "ACME") == {"ACME-1"}, "pr ticket keys take the project they are given"
