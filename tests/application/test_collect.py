import datetime as dt
import json
import threading
import types
from dataclasses import replace

import pytest

from builders import EPIC, PR_ONE, PR_THREE, PR_TWO, STATED, TICKETS, TICKET_DETAIL, board, light_node, make_epic, make_settings
from magi.adapters import github, paths, storage
from magi.application.refresh import Refresh, saved_board
from magi.application.upgrades import UPGRADES
from magi.domain import changes, review, status
from magi.domain.entities import Ticket, TicketDetail


class FakeStore:
    """The refresh's files in memory, kept as json so they read back the way the json files do."""

    def __init__(self):
        self.files = {}

    def read(self, name):
        assert name in paths.REFRESH_FILES, f"the real store has no file for {name}"
        return json.loads(self.files[name]) if name in self.files else None

    def write(self, name, data):
        assert name in paths.REFRESH_FILES, f"the real store has no file for {name}"
        self.files[name] = json.dumps(data, default=storage.encode)


class FakeClock:
    def __init__(self, at):
        self.at = at

    def time(self):
        return self.at

    def now(self):
        return dt.datetime(2026, 10, 25, 9, 0)


def in_order(fn, items):
    return [fn(item) for item in items]


def refresh_with(tickets=None, pull_requests=None, at=1600.0):
    store, clock = FakeStore(), FakeClock(at)
    return Refresh(tickets, pull_requests, store, clock, in_order), store, clock


def test_cached_board_reads_back(tmp_path):
    found = board([PR_ONE, PR_TWO])
    storage.write(tmp_path / "cache.json", {"board": found})
    again = saved_board(storage.read(tmp_path / "cache.json")["board"])
    assert again == found, "a cached board reads back as the same board"


def test_state_write():
    refresh, store, _ = refresh_with()
    refresh.save_state({"tickets": {}}, [], {})
    assert store.read("state") == {"snapshot": {"tickets": {}}, "changes": [], "histories": {}}, "the state is saved through storage"


def test_refetch_changed():
    asked, changed = [], []
    tickets = types.SimpleNamespace(changed_since=lambda keys, minutes, linked_to=(): changed.append((sorted(keys), minutes)) or {"A-2"})
    refresh, store, clock = refresh_with(tickets)

    def fetch_one(key):
        asked.append(key)
        return f"{key} #{len(asked)}"
    first = refresh.refetch_changed("updated", ["A-1", "A-2"], fetch_one, 1000.0)
    assert sorted(asked) == ["A-1", "A-2"], "a first refresh fetches every key"
    assert changed == [], "a first refresh fetches every key"
    asked.clear()
    second = refresh.refetch_changed("updated", ["A-1", "A-2", "A-3"], fetch_one, 1600.0)
    assert changed == [(["A-1", "A-2"], 15)], "the next refresh asks jira what changed since the last one, with a margin"
    assert sorted(asked) == ["A-2", "A-3"], "only changed or new keys are fetched again"
    assert second["A-1"] == first["A-1"], "only changed or new keys are fetched again"
    refresh.refetch_changed("updated", ["A-3"], fetch_one, 2000.0)
    assert sorted(store.read("updated")["found"]) == ["A-3"], "keys that left the board leave the cache"
    changed.clear()
    clock.at = 2600.0
    refresh.refetch_changed("updated", ["A-3"], fetch_one, 2000.0)
    assert changed == [(["A-3"], 15)], "the window runs until jira is asked, not until the refresh started"
    assert store.read("updated")["at"] == 2000.0, "the window runs until jira is asked, not until the refresh started"


def test_refetch_changed_links():
    asked, linked = [], []
    tickets = types.SimpleNamespace(changed_since=lambda keys, minutes, linked_to=(): linked.append(sorted(linked_to)) or {"B-9"})
    refresh, _, _ = refresh_with(tickets)

    def fetch_one(key):
        asked.append(key)
        return {"links": [{"key": "B-9"}] if key == "A-1" else []}
    links = lambda detail: [link["key"] for link in detail["links"]]
    refresh.refetch_changed("updated", ["A-1", "A-2"], fetch_one, 1000.0, links)
    asked.clear()
    refresh.refetch_changed("updated", ["A-1", "A-2"], fetch_one, 1600.0, links)
    assert linked == [["A-1", "A-2"]], "jira is asked about the tickets linked to the cached ones"
    assert asked == ["A-1"], "a ticket is fetched again when a ticket it links to changed"


def test_collect_shows_my_prs_outside_the_team():
    mine = replace(PR_TWO, title="Bump a gem", head_ref_name="bump-gem", author={"login": "carol"})
    queries = []

    def search(query):
        queries.append(query)
        return [github.light_pr(light_node(mine))] if "author:carol" in query else []
    tickets = types.SimpleNamespace(
        fetch_my_tickets=lambda details: [], fetch_kanban=lambda settings, details: [], fetch_updated=lambda key: key,
        changed_since=lambda keys, minutes, linked_to=(): set(),
        fetch_epics=lambda settings: [EPIC], fetch_children=lambda key: [replace(t, prs=[]) for t in TICKETS])
    pull_requests = types.SimpleNamespace(search_prs=search, fetch_prs=lambda items: [mine for _ in items],
                                          fetch_failed_checks=lambda items: [[] for _ in items],
                                          fetch_pr_states=lambda urls: {}, search_terms=github.search_terms)
    refresh, _, _ = refresh_with(tickets, pull_requests)
    found = refresh.collect(make_settings(github_user="carol"))
    assert "is:pr is:open archived:false org:acme author:alice author:bob author:carol" in queries, \
        "my own prs are searched with the team's, though i am not in the team"
    assert [pr.number for pr in found["prs"]] == [2], "my prs show among the team's even without a tracked ticket"
    assert [pr.number for pr in found["my_prs"]] == [2], "my prs show in mine even without a tracked ticket"


def test_a_merged_pr_keeps_its_history():
    mine = replace(PR_TWO, title="Bump a gem", head_ref_name="bump-gem", author={"login": "carol"})
    shown = {"prs": [github.light_pr(light_node(mine))]}
    tickets = types.SimpleNamespace(
        fetch_my_tickets=lambda details: [], fetch_kanban=lambda settings, details: [], fetch_updated=lambda key: key,
        changed_since=lambda keys, minutes, linked_to=(): set(),
        fetch_epics=lambda settings: [EPIC], fetch_children=lambda key: [replace(t, prs=[]) for t in TICKETS])
    pull_requests = types.SimpleNamespace(search_prs=lambda query: shown["prs"] if "author:carol" in query else [],
                                          fetch_prs=lambda items: [mine for _ in items], fetch_failed_checks=lambda items: [[] for _ in items],
                                          fetch_pr_states=lambda urls: {url: "MERGED" for url in urls}, search_terms=github.search_terms)
    refresh, store, _ = refresh_with(tickets, pull_requests)
    settings = make_settings(github_user="carol")
    assert refresh.collect(settings)["histories"] == {mine.url: review.pr_events(mine)}, "the board carries the history of every pr on it"
    assert store.read("state")["histories"] == {mine.url: review.pr_events(mine)}, "every pr on the board has its history saved"
    shown["prs"] = []
    found = refresh.collect(settings)
    assert [(c["label"], c["group"]) for c in found["changes"]] == [("Merged", mine.url)], "a pr that left the board is merged"
    assert found["histories"] == {mine.url: review.pr_events(mine)}, "a merged pr keeps its history while its change shows"


def quiet_jira(**overrides):
    return types.SimpleNamespace(**{
        "fetch_my_tickets": lambda details: [], "fetch_kanban": lambda settings, details: [], "fetch_updated": lambda key: key,
        "changed_since": lambda keys, minutes, linked_to=(): set(),
        "fetch_epics": lambda settings: [EPIC], "fetch_children": lambda key: [replace(t, prs=[]) for t in TICKETS], **overrides})


NO_PRS = types.SimpleNamespace(search_prs=lambda query: [], fetch_prs=lambda items: [], fetch_pr_states=lambda urls: {},
                               fetch_failed_checks=lambda items: [[] for _ in items],
                               search_terms=github.search_terms)


def test_changes_saved_by_format_3_survive_the_upgrade(tmp_path):
    files = {name: tmp_path / path.name for name, path in paths.REFRESH_FILES.items()}
    old = {"at": "2026-10-25T08:00", "item": PR_ONE.url, "tone": "commented", "label": "New PR", "note": None, "aside": None,
           "subject": {"kind": "pr", "url": PR_ONE.url, "ref": "app#1", "title": PR_ONE.title}}
    moved = {"at": "2026-10-25T07:00", "item": STATED.jira_browse + "ACME-1", "tone": "waiting", "label": "En proceso", "note": None,
             "aside": "was: Tareas por hacer", "subject": changes.ticket_subject("ACME-1", STATED.jira_browse, "Ticket one")}
    pushed = {**old, "at": "2026-10-25T08:30", "tone": "waiting", "label": "New commits"}
    reviewed = {**old, "at": "2026-10-25T08:15", "label": "Commented", "aside": "new review"}
    joined = {**moved, "at": "2026-10-25T06:00", "item": STATED.jira_browse + "ACME-2", "label": "Finalizado", "note": "joins the epics",
              "aside": None, "subject": changes.ticket_subject("ACME-2", STATED.jira_browse, "Ticket two")}
    taken = changes.snapshot([EPIC], {EPIC.key: [replace(t, prs=[]) for t in TICKETS]}, [], STATED)
    saved = {**taken, "tickets": {t.key: t.status for t in TICKETS}}
    files["state"].write_text(json.dumps({"version": 3, "snapshot": saved, "changes": [pushed, reviewed, old, moved, joined]}))
    store = storage.JsonFiles(files, UPGRADES)
    untitled = {**taken, "tickets": {t.key: {"status": t.status, "summary": None} for t in TICKETS}}
    unsigned = {**old["subject"], "author": None}
    assert store.read("state") == {"snapshot": untitled, "histories": {}, "changes": [
        {**pushed, "subject": unsigned, "group": old["item"], "told": True},
        {**reviewed, "subject": unsigned, "group": old["item"], "told": True},
        {**old, "subject": unsigned, "group": old["item"], "told": False},
        {**moved, "label": "In Progress", "aside": "was: Todo", "group": moved["item"], "told": False},
        {**joined, "label": "Done", "group": joined["item"], "told": False}]}, \
        "a state saved by format 3 keeps its snapshot, starts with no pr histories, reads its ticket statuses in english, " \
        "and leaves pushes and new reviews to the pr's history"
    found = Refresh(quiet_jira(), NO_PRS, store, FakeClock(1600.0), in_order).collect(STATED)
    assert [c["label"] for c in found["changes"]] == ["New commits", "Commented", "New PR", "In Progress", "Done"], \
        "the changes of the last 24 hours outlive an upgrade that changes how they are saved"


def test_a_snapshot_saved_by_format_4_survives_the_upgrade(tmp_path):
    files = {name: tmp_path / path.name for name, path in paths.REFRESH_FILES.items()}
    statuses = {**{t.key: t.status for t in TICKETS}, "ACME-9": "En proceso"}
    taken = {"epics": {EPIC.key: {"summary": EPIC.summary, "tickets": list(statuses)}}, "tickets": statuses, "prs": {}}
    files["state"].write_text(json.dumps({"version": 4, "snapshot": taken, "changes": [], "histories": {}}))
    store = storage.JsonFiles(files, UPGRADES)
    assert store.read("state")["snapshot"]["tickets"] == {key: {"status": status, "summary": None} for key, status in statuses.items()}, \
        "a snapshot saved by format 4 keeps its ticket statuses, without the titles it never saved"
    found = Refresh(quiet_jira(), NO_PRS, store, FakeClock(1600.0), in_order).collect(STATED)
    assert [changes.change_text(c) for c in found["changes"]] == ["ACME-9 (cancelled or moved)"], \
        "the first refresh after the upgrade still tells a ticket that left the epics, by its key alone"


def test_a_state_saved_by_format_5_survives_the_upgrade(tmp_path):
    files = {name: tmp_path / path.name for name, path in paths.REFRESH_FILES.items()}
    taken = changes.snapshot([EPIC], {EPIC.key: [replace(t, prs=[]) for t in TICKETS]}, [], STATED)
    moved = {"at": "2026-10-25T07:00", "item": STATED.jira_browse + "ACME-1", "group": STATED.jira_browse + "ACME-1", "tone": "waiting",
             "label": "In Progress", "note": None, "aside": "was: Todo", "told": False,
             "subject": changes.ticket_subject("ACME-1", STATED.jira_browse, "Ticket one")}
    files["state"].write_text(json.dumps({"version": 5, "snapshot": taken, "changes": [moved], "histories": {}}))
    store = storage.JsonFiles(files, UPGRADES)
    assert store.read("state") == {"snapshot": taken, "changes": [moved], "histories": {}}, \
        "a state saved by format 5 reads as it was: only the saved prs changed shape"


def test_a_state_saved_by_format_6_survives_the_upgrade(tmp_path):
    files = {name: tmp_path / path.name for name, path in paths.REFRESH_FILES.items()}
    taken = changes.snapshot([], {}, [PR_ONE], STATED)
    merged = {"at": "2026-10-25T07:00", "item": PR_ONE.url, "group": PR_ONE.url, "tone": "good", "label": "Merged", "note": None,
              "aside": None, "told": False, "subject": changes.pr_subject(PR_ONE.url, "app#1", PR_ONE.title, "alice")}
    older = {**taken, "prs": {url: {k: v for k, v in pr.items() if k != "author"} for url, pr in taken["prs"].items()}}
    unsigned = {**merged, "subject": {k: v for k, v in merged["subject"].items() if k != "author"}}
    files["state"].write_text(json.dumps({"version": 6, "snapshot": older, "changes": [unsigned], "histories": {}}))
    found = storage.JsonFiles(files, UPGRADES).read("state")
    assert found["snapshot"]["prs"][PR_ONE.url]["author"] is None, "a pr in a snapshot saved by format 6 reads with no author"
    assert found["changes"][0]["subject"]["author"] is None, "a pr change saved by format 6 reads with no author"


def test_known_epics_load_their_tickets_while_jira_lists_the_epics():
    new = make_epic(key="ACME-200", summary="Epic two")
    epics, children, overlapped = [EPIC], [], []
    asked = threading.Event()

    def fetch_epics(settings):
        overlapped.append(asked.wait(1))
        return epics

    def fetch_children(key):
        children.append(key)
        asked.set()
        return [replace(t, prs=[]) for t in TICKETS]
    refresh, _, _ = refresh_with(quiet_jira(fetch_epics=fetch_epics, fetch_children=fetch_children), NO_PRS)
    refresh.collect(STATED)
    asked.clear()
    children.clear()
    epics[:] = [new]
    found = refresh.collect(STATED)
    assert overlapped == [False, True], "a refresh asks for the tickets of the epics it knew while jira lists the epics"
    assert children == [EPIC.key, new.key], "an epic new to the board has its tickets asked once jira lists it"
    assert list(found["tickets_by_epic"]) == [new.key], "the board keeps only the epics jira lists now"


def test_jira_is_asked_what_changed_while_the_tickets_load():
    asked = threading.Event()
    overlapped = []

    def fetch_children(key):
        overlapped.append(asked.wait(1))
        return [replace(t, prs=[]) for t in TICKETS]
    changed, updated = [], []

    def changed_since(keys, minutes, linked_to=()):
        changed.append(sorted(keys))
        asked.set()
        return {"ACME-1"}
    jira = quiet_jira(fetch_children=fetch_children, changed_since=changed_since, fetch_updated=lambda key: updated.append(key) or key)
    refresh, _, _ = refresh_with(jira, NO_PRS)
    refresh.collect(STATED)
    refresh.collect(STATED)
    assert overlapped == [False, True], "a refresh asks jira which tickets changed while the epics' tickets load"
    assert changed == [["ACME-1"]], "jira is asked once per refresh which tickets changed"
    assert updated == ["ACME-1", "ACME-1"], "a ticket jira names as changed has its update time asked again"


def test_an_epic_jira_no_longer_lists_cannot_break_the_refresh():
    new = make_epic(key="ACME-200", summary="Epic two")
    epics, failing = [EPIC], set()

    def fetch_children(key):
        if key in failing:
            raise RuntimeError(f"{key} does not exist")
        return [replace(t, prs=[]) for t in TICKETS]
    refresh, _, _ = refresh_with(quiet_jira(fetch_epics=lambda settings: epics, fetch_children=fetch_children), NO_PRS)
    refresh.collect(STATED)
    epics[:], failing = [new], {EPIC.key}
    assert list(refresh.collect(STATED)["tickets_by_epic"]) == [new.key], "an epic deleted since the last refresh is left out"
    failing = {EPIC.key, new.key}
    with pytest.raises(RuntimeError):
        refresh.collect(STATED)


def test_collect():
    three =replace(PR_THREE, url="https://github.com/acme/renamed/pull/3")
    lights = {"team": [light_node(PR_TWO)], "review": [light_node(three), light_node(PR_ONE)], "open": [light_node(PR_ONE)]}
    details = {1: PR_ONE, 2: PR_TWO, 3: three}
    queries, asked = [], []

    def search(query):
        queries.append(query)
        kind = "team" if "author:" in query else "review" if "user-review-requested" in query else "merged" if "is:merged" in query else "open"
        return [github.light_pr(node) for node in lights.get(kind, [])]

    def details_of(items):
        items = list(items)
        asked.append(items)
        current = {n["number"]: n for kind in lights.values() for n in kind}
        return [replace(details[number], updated_at=current[number]["updatedAt"]) for _, number in items]
    asked_jira, viewed = [], []
    tickets = types.SimpleNamespace(
        fetch_ticket=lambda key: viewed.append(key) or Ticket(key=key, summary="Ticket seven", status="En proceso"),
        fetch_my_tickets=lambda details: [Ticket(key="ACME-9", summary="Ticket nine", status="En proceso", detail=details(["ACME-9"])["ACME-9"])],
        fetch_kanban=lambda settings, details: [Ticket(key="ACME-8", summary="Ticket eight", status="En revisión", assignee="Ana",
                                                       detail=details(["ACME-8"])["ACME-8"])],
        fetch_ticket_detail=lambda key: replace(TICKET_DETAIL, description=f"{key} detail", links=[{"key": "ACME-50"}]),
        fetch_updated=lambda key: f"{key} updated",
        changed_since=lambda keys, minutes, linked_to=(): asked_jira.append((sorted(keys), sorted(linked_to))) or set(),
        fetch_epics=lambda settings: [EPIC], fetch_children=lambda key: [replace(t, prs=[]) for t in TICKETS])
    checked = []

    def failed_checks_of(items):
        items = list(items)
        checked.append(items)
        return [[{"name": "rspec", "url": "https://ci/rspec"}] for _ in items]
    pull_requests = types.SimpleNamespace(search_prs=search, fetch_prs=details_of, fetch_pr_states=lambda urls: {},
                                          fetch_failed_checks=failed_checks_of, search_terms=github.search_terms)
    refresh, store, _ = refresh_with(tickets, pull_requests)
    found = refresh.collect(STATED)
    assert "is:pr is:open archived:false org:acme author:alice author:bob" in queries, "the team's prs come from one search naming every author"
    assert "is:pr is:open archived:false org:acme user-review-requested:@me" in queries, "review requests and ticket keys are searched too"
    assert "is:pr is:open archived:false org:acme ACME-100 OR ACME-1" in queries, "review requests and ticket keys are searched too"
    assert not any("is:merged" in query for query in queries), "merged prs are not searched: nothing on the board reads them"
    assert "attention" not in found, "the board has no attention box"
    assert len(asked) == 1, "every pr on the board is fetched once, in one go"
    assert sorted(asked[0]) == [("acme/app", 1), ("acme/billing-reconciliation-service", 2), ("acme/renamed", 3)], \
        "every pr on the board is fetched once, in one go"
    assert [pr.number for pr in found["review_prs"]] == [3, 1], "review requests keep their order"
    assert sorted(store.read("state")["histories"]) == sorted([PR_ONE.url, PR_TWO.url, three.url]), \
        "every pr on the board, review requests alone included, has its history saved"
    assert found["histories"] == store.read("state")["histories"], "the board carries every history the refresh saved"
    active = [t for t in found["by_key"].values() if t.column in status.ACTIVE_COLUMNS]
    assert active, "active tickets take their update time from the update cache"
    assert all(t.updated == f"{t.key} updated" for t in active), "active tickets take their update time from the update cache"
    assert sorted(store.read("updated")["found"]) == sorted(t.key for t in active), \
        "active tickets take their update time from the update cache"
    assert found["my_tickets"][0].detail.description == "ACME-9 detail", "my tickets take their details from their own cache"
    assert list(store.read("my_tickets")["found"]) == ["ACME-9"], "my tickets take their details from their own cache"
    assert found["kanban"][0].detail.description == "ACME-8 detail", "the kanban board's tickets take their details from their own cache"
    assert list(store.read("kanban")["found"]) == ["ACME-8"], "the kanban board's tickets take their details from their own cache"
    refresh.ticket("ACME-7")
    asked.clear()
    again = refresh.collect(STATED)
    refresh.ticket("ACME-7")
    assert viewed == ["ACME-7", "ACME-7"], "a refresh forgets the tickets v fetched, so the next v shows Jira as it is now"
    assert sorted(asked_jira) == sorted([(sorted(t.key for t in active), []), (["ACME-9"], ["ACME-9"]), (["ACME-8"], ["ACME-8"])]), \
        "the next refresh asks jira what changed, and about the tickets linked to mine and to the kanban board's"
    assert isinstance(again["my_tickets"][0].detail, TicketDetail), "my ticket details read back from the cache are entities"
    assert again["my_tickets"][0].detail.description == "ACME-9 detail", "my ticket details read back from the cache are entities"
    assert isinstance(again["kanban"][0].detail, TicketDetail), "the kanban board's ticket details read back from the cache are entities"
    assert asked in ([], [[]]), "an unchanged pr is not fetched again"
    lights["open"] = [light_node(PR_ONE, updated="2026-10-25T08:00:00Z")]
    lights["review"] = [light_node(three), light_node(PR_ONE, updated="2026-10-25T08:00:00Z")]
    assert checked[0] == [], "a board with no pr whose ci failed asks for no failed checks"
    lights["team"] = [light_node(PR_TWO, ci="FAILURE")]
    asked.clear()
    found = refresh.collect(STATED)
    assert asked == [[("acme/app", 1)]], "only the pr updated since the last refresh is fetched again"
    assert {pr.number: pr.ci for pr in found["prs"]} == {1: "passing", 2: "failing"}, "ci comes from the search even when the detail is reused"
    assert {pr.number: pr.failed_checks for pr in found["prs"]} == {1: [], 2: [{"name": "rspec", "url": "https://ci/rspec"}]}, \
        "the failed checks are asked on every refresh, even when the detail is reused"
    assert checked[-1] == [("acme/billing-reconciliation-service", 2)], "only the prs whose ci failed are asked for their failed checks"


def test_ticket():
    asked = []

    def fetch_ticket(key):
        asked.append(key)
        if len(asked) == 1:
            raise RuntimeError("acli timed out")
        return Ticket(key=key, summary="Ticket one", status="En proceso")

    refresh, _, _ = refresh_with(types.SimpleNamespace(fetch_ticket=fetch_ticket))
    try:
        refresh.ticket("ACME-1")
    except RuntimeError:
        pass
    first, again = refresh.ticket("ACME-1"), refresh.ticket("ACME-1")
    assert first == again == Ticket(key="ACME-1", summary="Ticket one", status="En proceso"), "a ticket comes from the tickets port"
    assert asked == ["ACME-1", "ACME-1"], "a failed fetch is not kept, and a fetched ticket is asked of Jira once until the next refresh"
