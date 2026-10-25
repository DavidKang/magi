import re

from builders import CHANGES, NOTE, PR_TWO, THREAD, light_node, pr_node
from tarkon.adapters import github, process
from tarkon.domain.entities import FoundPr


def test_search_prs(monkeypatch):
    seen = []
    monkeypatch.setattr(process, "run_json", lambda cmd: seen.append(cmd) or {"data": {"search": {"nodes": [
        {**light_node(PR_TWO, ci="FAILURE"), "author": None}]}}})
    found = github.search_prs("is:pr is:open org:acme author:alice")
    query = next(arg for arg in seen[0] if arg.startswith("query="))
    assert seen[0][:3] == ["gh", "api", "graphql"], "pr searches go through graphql, not the rest search api"
    assert 'search(type: ISSUE, query: "is:pr is:open org:acme author:alice", first: 100)' in query, \
        "pr searches go through graphql, not the rest search api"
    assert (found == [FoundPr(
          url=PR_TWO.url, number=2, updated_at="2026-10-24T10:00:00Z", title=PR_TWO.title, head_ref_name="ACME-2-y",
          mergeable="MERGEABLE", author={"login": "ghost"}, name_with_owner="acme/billing-reconciliation-service",
          repo="billing-reconciliation-service", ci="failing")]), "a search returns light prs with their ci, repo and update time"
    assert not any(hasattr(module, name) for module in (process, github) for name in
                   ("search_team_prs", "search_open_prs", "search_merged_prs", "search_review_requested_from_me")), "the rest pr searches are gone"


def test_pr_states(monkeypatch):
    seen = []
    monkeypatch.setattr(process, "run_json", lambda cmd: seen.append(cmd) or {"data": {
        "pr0": {"pullRequest": {"state": "MERGED"}}, "pr1": {"pullRequest": {"state": "CLOSED"}}}})
    urls = ["https://github.com/acme/app/pull/8", "https://github.com/acme/web/pull/9"]
    states = github.fetch_pr_states(urls)
    query = next(arg for arg in seen[0] if arg.startswith("query="))
    assert len(seen) == 1, "vanished pr states come from one graphql call"
    assert states == {urls[0]: "MERGED", urls[1]: "CLOSED"}, "vanished pr states come from one graphql call"
    assert 'name: "web"' in query, "vanished pr states come from one graphql call"
    assert "pullRequest(number: 9)" in query, "vanished pr states come from one graphql call"
    assert github.fetch_pr_states([]) == {}, "nothing vanished asks nothing"
    assert len(seen) == 1, "nothing vanished asks nothing"


def test_pr_fetch():
    rollups = [{"state": "FAILURE"}, {"state": "PENDING"}, {"state": "SUCCESS"}, None]
    seen, run_json = [], process.run_json

    def graph(cmd):
        seen.append(cmd)
        query = next(arg for arg in cmd if arg.startswith("query="))
        numbers = [int(n) for n in re.findall(r"pullRequest\(number: (\d+)\)", query)]
        return {"data": {f"pr{i}": pr_node(n, rollups[n % 4]) for i, n in enumerate(numbers)}}

    process.run_json = graph
    try:
        prs = github.fetch_prs([("acme/app", 2), ("acme/app", 3)])
        many = github.fetch_prs([("acme/app", n) for n in range(25)])
    finally:
        process.run_json = run_json
    query = next(arg for arg in seen[0] if arg.startswith("query="))
    assert len(seen) == 10, "prs come from one graphql call per batch of 3"
    assert all("graphql" in cmd for cmd in seen), "prs come from one graphql call per batch of 3"
    assert len(many) == 25, "prs come from one graphql call per batch of 3"
    assert 'owner: "acme"' in query, "pr fetch asks for each pr by repo and number"
    assert 'name: "app"' in query, "pr fetch asks for each pr by repo and number"
    assert "pullRequest(number: 2)" in query, "pr fetch asks for each pr by repo and number"
    assert "pullRequest(number: 3)" in query, "pr fetch asks for each pr by repo and number"
    assert [pr.number for pr in many] == list(range(25)), "pr fetch keeps the order it was asked"
    assert prs[0].threads == [THREAD], "pr fetch keeps only unresolved review threads"
    assert prs[0].conversation == [NOTE], "pr fetch keeps conversation comments from people, not bots"
    assert prs[0].reviews == [CHANGES], "pr fetch flattens reviews, review requests and commits"
    assert len(prs[0].review_requests) == 1, "pr fetch flattens reviews, review requests and commits"
    assert [c["committedDate"] for c in prs[0].commits] == ["2026-10-21T10:00:00Z", "2026-10-22T10:00:00Z"], \
        "pr fetch flattens reviews, review requests and commits"
    assert [pr.ci for pr in many[:4]] == ["failing", "running", "passing", "none"], "pr ci comes from the last commit's check rollup"
    assert prs[0].repo == "app", "pr fetch names the repo"
    assert "commits(last: 100) { nodes { commit { committedDate } } }" in query, "pr fetch asks for the check rollup of the head commit only"
    assert "head: commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }" in query, \
        "pr fetch asks for the check rollup of the head commit only"
    node = pr_node(5, None)["pullRequest"]
    ghost = {**node, "author": None, "reviews": {"nodes": [{**CHANGES, "author": None}]},
             "reviewThreads": {"nodes": [{**THREAD, "comments": {"nodes": [{**THREAD["comments"][0], "author": None}]}}]}}
    pr = github.pr_from_graph(ghost, "acme/app")
    assert pr.author == {"login": "ghost"}, "a deleted account reads as ghost"
    assert pr.reviews[0]["author"] == {"login": "ghost"}, "a deleted account reads as ghost"
    assert pr.threads[0]["comments"][0]["author"] == {"login": "ghost"}, "a deleted account reads as ghost"
    assert all(re.search(rf"\b{name}\b", query) for name in ("login", "body", "createdAt", "diffHunk", "url")), \
        "pr fetch asks for every comment field the popup shows"
