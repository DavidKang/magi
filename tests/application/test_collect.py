import datetime as dt
import json
import types
from dataclasses import replace

from builders import EPIC, PR_ONE, PR_THREE, PR_TWO, STATED, TICKETS, TICKET_DETAIL, board, light_node
from tarkon.adapters import github, paths, storage
from tarkon.application.refresh import Refresh, saved_board
from tarkon.domain import attention
from tarkon.domain.entities import Ticket, TicketDetail


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
    found = {key: value for key, value in board([PR_ONE, PR_TWO]).items() if key != "out"}
    storage.write(tmp_path / "cache.json", {"board": found})
    again = saved_board(storage.read(tmp_path / "cache.json")["board"])
    assert again == found, "a cached board reads back as the same board"


def test_state_write():
    refresh, store, _ = refresh_with()
    refresh.save_state({"tickets": {}}, [])
    assert store.read("state") == {"snapshot": {"tickets": {}}, "changes": []}, "the state is saved through storage"


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


def test_collect():
    three = replace(PR_THREE, url="https://github.com/acme/renamed/pull/3")
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
    asked_jira = []
    tickets = types.SimpleNamespace(
        fetch_my_tickets=lambda details: [Ticket(key="ACME-9", summary="Ticket nine", status="En proceso", detail=details(["ACME-9"])["ACME-9"])],
        fetch_ticket_detail=lambda key: replace(TICKET_DETAIL, description=f"{key} detail", links=[{"key": "ACME-50"}]),
        fetch_updated=lambda key: f"{key} updated",
        changed_since=lambda keys, minutes, linked_to=(): asked_jira.append((sorted(keys), sorted(linked_to))) or set(),
        fetch_epics=lambda settings: [EPIC], fetch_children=lambda key: [replace(t, prs=[]) for t in TICKETS])
    pull_requests = types.SimpleNamespace(search_prs=search, fetch_prs=details_of, fetch_pr_states=lambda urls: {},
                                          search_terms=github.search_terms)
    refresh, store, _ = refresh_with(tickets, pull_requests)
    found = refresh.collect(STATED)
    assert "is:pr is:open archived:false org:acme author:alice author:bob" in queries, "the team's prs come from one search naming every author"
    assert "is:pr is:open archived:false org:acme user-review-requested:@me" in queries, "review requests and ticket keys are searched too"
    assert "is:pr is:open archived:false org:acme ACME-100 OR ACME-1" in queries, "review requests and ticket keys are searched too"
    assert "is:pr is:merged org:acme ACME-1" in queries, "review requests and ticket keys are searched too"
    assert len(asked) == 1, "every pr on the board is fetched once, in one go"
    assert sorted(asked[0]) == [("acme/app", 1), ("acme/billing-reconciliation-service", 2), ("acme/renamed", 3)], \
        "every pr on the board is fetched once, in one go"
    assert [pr.number for pr in found["review_prs"]] == [3, 1], "review requests keep their order"
    active = [t for t in found["by_key"].values() if t.column in attention.ACTIVE_COLUMNS]
    assert active, "active tickets take their update time from the update cache"
    assert all(t.updated == f"{t.key} updated" for t in active), "active tickets take their update time from the update cache"
    assert sorted(store.read("updated")["found"]) == sorted(t.key for t in active), \
        "active tickets take their update time from the update cache"
    assert found["my_tickets"][0].detail.description == "ACME-9 detail", "my tickets take their details from their own cache"
    assert list(store.read("my_tickets")["found"]) == ["ACME-9"], "my tickets take their details from their own cache"
    asked.clear()
    again = refresh.collect(STATED)
    assert sorted(asked_jira) == sorted([(sorted(t.key for t in active), []), (["ACME-9"], ["ACME-9"])]), \
        "the next refresh asks jira what changed, and about the tickets linked to mine"
    assert isinstance(again["my_tickets"][0].detail, TicketDetail), "my ticket details read back from the cache are entities"
    assert again["my_tickets"][0].detail.description == "ACME-9 detail", "my ticket details read back from the cache are entities"
    assert asked in ([], [[]]), "an unchanged pr is not fetched again"
    lights["open"] = [light_node(PR_ONE, updated="2026-10-25T08:00:00Z")]
    lights["review"] = [light_node(three), light_node(PR_ONE, updated="2026-10-25T08:00:00Z")]
    lights["team"] = [light_node(PR_TWO, ci="FAILURE")]
    asked.clear()
    found = refresh.collect(STATED)
    assert asked == [[("acme/app", 1)]], "only the pr updated since the last refresh is fetched again"
    assert {pr.number: pr.ci for pr in found["prs"]} == {1: "passing", 2: "failing"}, "ci comes from the search even when the detail is reused"
