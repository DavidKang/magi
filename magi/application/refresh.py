"""Collect the board: fetch epics, tickets and PRs, cache what did not change, and save the snapshot the next run compares to."""

import dataclasses
import math
from concurrent.futures import ThreadPoolExecutor

from ..domain.attention import ACTIVE_COLUMNS, attention_items
from ..domain.changes import pr_subject, recent_changes, snapshot, vanished_prs
from ..domain.entities import Epic, PullRequest, TicketDetail, ticket_from
from ..domain.histories import kept_histories, pr_histories
from ..domain.keys import ticket_keys_in

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
        fresh = dict(zip((pr.url for pr in stale), self.pull_requests.fetch_prs((pr.name_with_owner, pr.number) for pr in stale)))
        details = {pr.url: fresh.get(pr.url) or cached[pr.url] for pr in found}
        self.store.write("prs", {"prs": details})
        # CI and mergeability change without touching updatedAt, so they always come from the search.
        return {pr.url: dataclasses.replace(details[pr.url], ci=pr.ci, mergeable=pr.mergeable) for pr in found}

    def refetch_changed(self, name, keys, fetch_one, started, linked=None, rebuild=None):
        """fetch_one(key) for the keys Jira changed since the last refresh, or never seen; the rest come from the store.

        linked(found) names the tickets a cached value shows, so a change to one of them fetches the value again;
        rebuild(value) turns a value read back from the store into what fetch_one returns.
        """
        cache = self.store.read(name)
        found = {key: rebuild(value) if rebuild else value for key, value in cache["found"].items()} if cache else {}
        known = [key for key in keys if key in found]
        changed = set()
        if known:
            minutes = math.ceil((self.clock.time() - cache["at"]) / 60) + JIRA_MARGIN_MINUTES
            changed = self.tickets.changed_since(known, minutes, known if linked else ())
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
        my_tickets = pool.submit(tickets.fetch_my_tickets,
                                 lambda keys: self.refetch_changed("my_tickets", keys, tickets.fetch_ticket_detail, started,
                                                                   lambda detail: [link["key"] for link in detail.links],
                                                                   lambda value: TicketDetail(**value)))
        epics = tickets.fetch_epics(settings)
        epic_keys = [epic.key for epic in epics]
        tickets_by_epic = dict(zip(epic_keys, parallel(tickets.fetch_children, epic_keys)))
        by_key = {t.key: t for ts in tickets_by_epic.values() for t in ts}

        active = [t for t in by_key.values() if t.column in ACTIVE_COLUMNS]
        updated = pool.submit(self.refetch_changed, "updated", [t.key for t in active], tickets.fetch_updated, started)
        search_keys = epic_keys + [k for k, t in by_key.items() if t.column != "done"]
        active_keys = [k for k, t in by_key.items() if t.column in {"doing", "review"}]
        merged_prs = pool.submit(parallel, pull_requests.search_prs,
                                 [f"is:pr is:merged {org} {' '.join(terms)}" for terms in pull_requests.search_terms(active_keys)])
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

        merged_by_ticket = {}
        for merged in (pr for found in merged_prs.result() for pr in found):
            subject = pr_subject(merged.url, f"{merged.repo}#{merged.number}", merged.title)
            for k in ticket_keys_in(dataclasses.replace(merged, head_ref_name=""), settings.jira_project):
                if k in active_keys:
                    merged_by_ticket.setdefault(k, []).append(subject)
        my_tickets = my_tickets.result()
        found_updated = updated.result()
        for ticket in active:
            ticket.updated = found_updated[ticket.key]

        state = self.store.read("state")
        now = snapshot(epics, tickets_by_epic, {pr.url: pr for pr in prs + review_prs}.values(), settings)
        stamp = self.clock.now()
        ended = pull_requests.fetch_pr_states(vanished_prs(state["snapshot"], now) if state else [])
        changes = recent_changes(state, now, {k: t.summary for k, t in by_key.items()}, stamp, ended, settings)
        histories = pr_histories(prs + review_prs, kept_histories(state["histories"] if state else {}, changes or []))

        self.save_state(now, changes or [], histories)
        pool.shutdown()
        return {"epics": epics, "tickets_by_epic": tickets_by_epic, "by_key": by_key, "prs": prs, "review_prs": review_prs,
                "my_prs": [pr for pr in prs if pr.author["login"] == settings.github_user], "my_tickets": my_tickets,
                "attention": attention_items(list(by_key.values()), prs, merged_by_ticket, settings), "changes": changes or [],
                "histories": histories,
                "merged_by_ticket": merged_by_ticket, "now": now}


def saved_board(data):
    """A board collect returned, read back from json: its epics, tickets and PRs rebuilt as entities."""
    tickets_by_epic = {key: [ticket_from(t) for t in tickets] for key, tickets in data["tickets_by_epic"].items()}
    return {**data, "epics": [Epic(**e) for e in data["epics"]], "tickets_by_epic": tickets_by_epic,
            "by_key": {t.key: t for tickets in tickets_by_epic.values() for t in tickets},
            "prs": [PullRequest(**pr) for pr in data["prs"]], "review_prs": [PullRequest(**pr) for pr in data["review_prs"]],
            "my_prs": [PullRequest(**pr) for pr in data["my_prs"]], "my_tickets": [ticket_from(t) for t in data["my_tickets"]]}
