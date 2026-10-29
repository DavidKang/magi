"""Collect the board: fetch epics, tickets and PRs, cache what did not change, and save the snapshot the next run compares to."""

import dataclasses
import math
from concurrent.futures import ThreadPoolExecutor

from ..domain.changes import recent_changes, snapshot, snapshot_epics, vanished_prs
from ..domain.entities import Epic, PullRequest, TicketDetail, ticket_from
from ..domain.histories import kept_histories, pr_histories
from ..domain.keys import ticket_keys_in
from ..domain.status import ACTIVE_COLUMNS

# Minutes added to the time since the last refresh when asking Jira what changed, for clock skew and slow refreshes.
JIRA_MARGIN_MINUTES = 5
OPEN_PRS = "is:pr is:open archived:false"


class Refresh:
    """The refresh, wired to its ports (magi.application.ports); parallel(fn, items) maps fn over items at once."""

    def __init__(self, tickets, pull_requests, store, clock, parallel):
        self.tickets, self.pull_requests, self.store, self.clock, self.parallel = tickets, pull_requests, store, clock, parallel
        self.seen_tickets = {}

    def ticket(self, key):
        """One ticket with its detail, asked of Jira once until the next refresh."""
        if key not in self.seen_tickets:
            self.seen_tickets[key] = self.tickets.fetch_ticket(key)
        return self.seen_tickets[key]

    def save_state(self, snapshot, changes, histories):
        self.store.write("state", {"snapshot": snapshot, "changes": changes, "histories": histories})

    def pr_details(self, found):
        """Full PRs for the light ones a search found: fetched again only when a PR changed since the last refresh."""
        cached = {url: PullRequest(**pr) for url, pr in (self.store.read("prs") or {}).get("prs", {}).items()}
        stale = [pr for pr in found if pr.url not in cached or cached[pr.url].updated_at != pr.updated_at]
        failing = [pr for pr in found if pr.ci == "failing"]
        with ThreadPoolExecutor(max_workers=1) as pool:
            checks = pool.submit(self.pull_requests.fetch_failed_checks, [(pr.name_with_owner, pr.number) for pr in failing])
            fresh = dict(zip((pr.url for pr in stale), self.pull_requests.fetch_prs((pr.name_with_owner, pr.number) for pr in stale)))
        failed = dict(zip((pr.url for pr in failing), checks.result()))
        details = {pr.url: fresh.get(pr.url) or cached[pr.url] for pr in found}
        self.store.write("prs", {"prs": details})
        # CI, its failed checks and mergeability change without touching updatedAt, so they are asked on every refresh.
        return {pr.url: dataclasses.replace(details[pr.url], ci=pr.ci, failed_checks=failed.get(pr.url, []), mergeable=pr.mergeable)
                for pr in found}

    def known_children(self, epic_key):
        """An epic's tickets, asked before Jira lists the epics; None when Jira refuses, as it does for an epic since deleted."""
        try:
            return self.tickets.fetch_children(epic_key)
        except Exception:
            return None

    def cached_changes(self, name, keys=None, linked=None, rebuild=None):
        """What the store keeps under name, and which of its keys (of keys, when given) Jira changed since the last refresh."""
        cache = self.store.read(name)
        found = {key: rebuild(value) if rebuild else value for key, value in cache["found"].items()} if cache else {}
        known = [key for key in (found if keys is None else keys) if key in found]
        if not known:
            return found, set()
        minutes = math.ceil((self.clock.time() - cache["at"]) / 60) + JIRA_MARGIN_MINUTES
        return found, self.tickets.changed_since(known, minutes, known if linked else ())

    def refetch_changed(self, name, keys, fetch_one, started, linked=None, rebuild=None, cached=None):
        """fetch_one(key) for the keys Jira changed since the last refresh, or never seen; the rest come from the store.

        linked(found) names the tickets a cached value shows, so a change to one of them fetches the value again;
        rebuild(value) turns a value read back from the store into what fetch_one returns;
        cached is what cached_changes returned when asked before the keys were known.
        """
        found, changed = cached or self.cached_changes(name, keys, linked, rebuild)
        stale = [key for key in keys if key not in found or key in changed or (linked and changed & set(linked(found[key])))]
        found = {**{key: found[key] for key in keys if key in found}, **dict(zip(stale, self.parallel(fetch_one, stale)))}
        self.store.write(name, {"at": started, "found": found})
        return found

    def collect(self, settings):
        tickets, pull_requests, parallel = self.tickets, self.pull_requests, self.parallel
        started = self.clock.time()
        self.seen_tickets = {}
        pool = ThreadPoolExecutor(max_workers=8)
        org = f"org:{settings.github_org}"
        people = list(dict.fromkeys([*settings.team, settings.github_user]))
        authors = [people[start:start + 6] for start in range(0, len(people), 6)]
        team_prs = pool.submit(parallel, pull_requests.search_prs,
                               [f"{OPEN_PRS} {org} " + " ".join(f"author:{a}" for a in chunk) for chunk in authors])
        review_requested = pool.submit(pull_requests.search_prs, f"{OPEN_PRS} {org} user-review-requested:@me")
        def details(name):
            return lambda keys: self.refetch_changed(name, keys, tickets.fetch_ticket_detail, started,
                                                     lambda detail: [link["key"] for link in detail.links], lambda value: TicketDetail(**value))
        my_tickets = pool.submit(tickets.fetch_my_tickets, details("my_tickets"))
        kanban = pool.submit(tickets.fetch_kanban, settings, details("kanban"))
        # Asked before Jira lists the epics: the epics and tickets of the last refresh are rarely different.
        state = self.store.read("state")
        known_epics = snapshot_epics(state["snapshot"]) if state else []
        known_children = pool.submit(parallel, self.known_children, known_epics)
        updated_changes = pool.submit(self.cached_changes, "updated")
        epics = tickets.fetch_epics(settings)
        epic_keys = [epic.key for epic in epics]
        children = {key: found for key, found in zip(known_epics, known_children.result()) if found is not None}
        new_epics = [key for key in epic_keys if key not in children]
        children.update(zip(new_epics, parallel(tickets.fetch_children, new_epics)))
        tickets_by_epic = {key: children[key] for key in epic_keys}
        by_key = {t.key: t for ts in tickets_by_epic.values() for t in ts}

        active = [t for t in by_key.values() if t.column in ACTIVE_COLUMNS]
        updated = pool.submit(lambda: self.refetch_changed("updated", [t.key for t in active], tickets.fetch_updated, started,
                                                           cached=updated_changes.result()))
        search_keys = epic_keys + [k for k, t in by_key.items() if t.column != "done"]
        open_prs = parallel(pull_requests.search_prs,
                            [f"{OPEN_PRS} {org} {' '.join(terms)}" for terms in pull_requests.search_terms(search_keys)])
        candidates = {pr.url: pr for found in open_prs + team_prs.result() for pr in found}
        shown = [pr for pr in candidates.values()
                 if any(k in by_key for k in ticket_keys_in(pr, settings.jira_project)) or pr.author["login"] in people]
        requested = review_requested.result()
        detailed = self.pr_details(list({pr.url: pr for pr in shown + requested}.values()))
        prs = [detailed[pr.url] for pr in shown]
        for pr in prs:
            for k in ticket_keys_in(pr, settings.jira_project):
                if k in by_key:
                    by_key[k].prs.append(pr)
        review_prs = [detailed[pr.url] for pr in requested]

        my_tickets = my_tickets.result()
        found_updated = updated.result()
        for ticket in active:
            ticket.updated = found_updated[ticket.key]

        now = snapshot(epics, tickets_by_epic, {pr.url: pr for pr in prs + review_prs}.values(), settings)
        stamp = self.clock.now()
        ended = pull_requests.fetch_pr_states(vanished_prs(state["snapshot"], now) if state else [])
        changes = recent_changes(state, now, {k: t.summary for k, t in by_key.items()}, stamp, ended, settings)
        histories = pr_histories(prs + review_prs, kept_histories(state["histories"] if state else {}, changes or []))

        self.save_state(now, changes or [], histories)
        pool.shutdown()
        return {"epics": epics, "tickets_by_epic": tickets_by_epic, "by_key": by_key, "prs": prs, "review_prs": review_prs,
                "my_prs": [pr for pr in prs if pr.author["login"] == settings.github_user], "my_tickets": my_tickets,
                "kanban": kanban.result(), "changes": changes or [], "histories": histories, "now": now}


def saved_board(data):
    """A board collect returned, read back from json: its epics, tickets and PRs rebuilt as entities."""
    tickets_by_epic = {key: [ticket_from(t) for t in tickets] for key, tickets in data["tickets_by_epic"].items()}
    return {**data, "epics": [Epic(**e) for e in data["epics"]], "tickets_by_epic": tickets_by_epic,
            "by_key": {t.key: t for tickets in tickets_by_epic.values() for t in tickets},
            "prs": [PullRequest(**pr) for pr in data["prs"]], "review_prs": [PullRequest(**pr) for pr in data["review_prs"]],
            "my_prs": [PullRequest(**pr) for pr in data["my_prs"]], "my_tickets": [ticket_from(t) for t in data["my_tickets"]],
            "kanban": [ticket_from(t) for t in data["kanban"]]}
