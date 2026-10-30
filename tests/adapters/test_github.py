import re
import subprocess
from dataclasses import replace

import pytest

from builders import CHANGES, NOTE, PR_TWO, THREAD, checks_page, light_node, pr_node
from magi.adapters import github, process
from magi.domain.entities import FoundPr


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
          base_ref_name="main", head_ref_oid=PR_TWO.head_ref_oid, mergeable="MERGEABLE", author={"login": "ghost"},
          name_with_owner="acme/billing-reconciliation-service",
          repo="billing-reconciliation-service", ci="failing")]), "a search returns light prs with their ci, repo and update time"
    assert "contexts" not in query, "a search asks only for the ci state, leaving the failed checks to the prs whose ci failed"
    assert not any(hasattr(module, name) for module in (process, github) for name in
                   ("search_team_prs", "search_open_prs", "search_merged_prs", "search_review_requested_from_me")), "the rest pr searches are gone"


def test_conflicts_are_the_files_both_sides_changed(monkeypatch):
    answers = {"repos/acme/app/compare/main...a1": {"merge_base_commit": {"sha": "b0"}, "files": [{"filename": "app.py"}, {"filename": "README.md"}]},
               "repos/acme/app/compare/b0...main": {"files": [{"filename": "setup.py"}, {"filename": "README.md"}, {"filename": "app.py"}]},
               "repos/acme/web/compare/main...c2": {"merge_base_commit": {"sha": "d0"}, "files": [{"filename": "web.py"}]},
               "repos/acme/web/compare/d0...main": {"files": [{"filename": "setup.py"}]}}
    timeouts = []
    monkeypatch.setattr(process, "run_json", lambda cmd, timeout=None: timeouts.append(timeout) or answers[cmd[2]])
    assert github.fetch_conflicts([("acme/app", "main", "a1"), ("acme/web", "main", "c2")]) == [["README.md", "app.py"], []], \
        "a PR's conflicts are the files its branch and its base both changed since they parted, each PR in the order asked"
    assert timeouts == [github.COMPARE_TIMEOUT] * 4, "every compare gives up after COMPARE_TIMEOUT, so a hung one cannot hold up the refresh"


@pytest.mark.parametrize("error", [subprocess.CalledProcessError(1, "gh"), subprocess.TimeoutExpired("gh", github.COMPARE_TIMEOUT)])
def test_conflicts_a_failed_compare_lists_no_files(monkeypatch, error):
    def answer(cmd, timeout=None):
        if "acme/huge" in cmd[2]:
            raise error
        return {"merge_base_commit": {"sha": "b0"}, "files": [{"filename": "app.py"}]}
    monkeypatch.setattr(process, "run_json", answer)
    assert github.fetch_conflicts([("acme/huge", "main", "a1"), ("acme/app", "main", "c2")]) == [[], ["app.py"]], \
        "a compare GitHub refuses or never answers lists no files for that PR instead of failing the refresh"


def failed_checks_of(monkeypatch, node):
    """The failed checks fetched for PR_TWO when GitHub answers with node; the asked queries."""
    seen = []
    monkeypatch.setattr(process, "run_json", lambda cmd: seen.append(next(arg for arg in cmd if arg.startswith("query="))) or
                        {"data": {"pr0": {"pullRequest": node}}})
    return github.fetch_failed_checks([("acme/billing-reconciliation-service", 2)])[0], seen


def test_failed_checks_are_named(monkeypatch):
    checks = [{"name": "rspec", "conclusion": "FAILURE", "detailsUrl": "https://ci/rspec"},
              {"name": "lint", "conclusion": "SUCCESS", "detailsUrl": "https://ci/lint"},
              {"name": "deploy", "conclusion": None, "detailsUrl": None},
              {"name": "e2e", "conclusion": "TIMED_OUT", "detailsUrl": None},
              {"context": "ci/jenkins", "state": "ERROR", "targetUrl": "https://jenkins/1"},
              {"context": "ci/sonar", "state": "SUCCESS", "targetUrl": "https://sonar/1"},
              {"name": "cancelled", "conclusion": "CANCELLED", "detailsUrl": "https://ci/cancelled"},
              {"name": "startup", "conclusion": "STARTUP_FAILURE", "detailsUrl": "https://ci/startup"},
              {"name": "approval", "conclusion": "ACTION_REQUIRED", "detailsUrl": "https://ci/approval"},
              {"name": "local", "conclusion": "FAILURE", "detailsUrl": "file:///etc/hosts"},
              {"name": "plain", "conclusion": "FAILURE", "detailsUrl": "http://ci/plain"},
              {"name": "quoted", "conclusion": "FAILURE", "detailsUrl": "https://ci/a'b\"c"}]
    found, seen = failed_checks_of(monkeypatch, light_node(PR_TWO, ci="FAILURE", checks=checks))
    assert "contexts(first: 100)" in seen[0], "the failed checks come from the head commit's checks"
    checks_page = PR_TWO.url + "/checks"
    assert found == [{"name": "rspec", "url": "https://ci/rspec"}, {"name": "e2e", "url": checks_page},
                                   {"name": "ci/jenkins", "url": "https://jenkins/1"}, {"name": "cancelled", "url": "https://ci/cancelled"},
                                   {"name": "startup", "url": "https://ci/startup"}, {"name": "approval", "url": "https://ci/approval"},
                                   {"name": "local", "url": checks_page}, {"name": "plain", "url": checks_page},
                                   {"name": "quoted", "url": checks_page}], \
        "the failed check runs and commit statuses are kept, linked to their log when it is a plain https url, else to the pr's checks"


def test_failed_checks_are_asked_in_parallel_batches_of_3(monkeypatch):
    seen = []

    def graph(cmd):
        query = next(arg for arg in cmd if arg.startswith("query="))
        seen.append(query)
        numbers = [int(n) for n in re.findall(r"pullRequest\(number: (\d+)\)", query)]
        failed = [{"name": f"rspec {n}", "conclusion": "FAILURE", "detailsUrl": f"https://ci/{n}"} for n in numbers]
        return {"data": {f"pr{i}": {"pullRequest": light_node(replace(PR_TWO, number=n), ci="FAILURE", checks=[failed[i]])}
                         for i, n in enumerate(numbers)}}
    monkeypatch.setattr(process, "run_json", graph)
    found = github.fetch_failed_checks([("acme/app", n) for n in range(7)])
    assert [checks[0]["name"] for checks in found] == [f"rspec {n}" for n in range(7)], "each pr's failed checks come back in the order asked"
    assert len(seen) == 3, "the failed checks come from one graphql call per batch of 3 prs"
    assert github.fetch_failed_checks([]) == [] and len(seen) == 3, "no pr whose ci failed asks nothing"


def paged(monkeypatch, ci, pages):
    """PR_TWO's failed checks, its ci and checks in pages, each page but the last pointing at the next; the asked queries."""
    seen = []
    cursors = [f"c{n}" for n in range(1, len(pages))] + [None]

    def graph(cmd):
        query = next(arg for arg in cmd if arg.startswith("query="))
        seen.append(query)
        if "after:" not in query:
            return {"data": {"pr0": {"pullRequest": light_node(PR_TWO, ci=ci, checks=pages[0], after=cursors[0])}}}
        n = cursors.index(re.search(r'after: "(c\d+)"', query)[1]) + 1
        rollup = pages[n] and {"contexts": checks_page(pages[n], cursors[n])}
        return {"data": {"repository": {"pullRequest": {"commits": {"nodes": [{"commit": {"statusCheckRollup": rollup}}]}}}}}
    monkeypatch.setattr(process, "run_json", graph)
    return github.fetch_failed_checks([("acme/billing-reconciliation-service", 2)])[0], seen


def test_a_failed_rollup_with_over_100_checks_names_every_failed_one(monkeypatch):
    passing = [{"name": f"unit {n}", "conclusion": "SUCCESS", "detailsUrl": None} for n in range(100)]
    rspec = {"name": "rspec", "conclusion": "FAILURE", "detailsUrl": "https://ci/rspec"}
    lint = {"name": "lint", "conclusion": "FAILURE", "detailsUrl": "https://ci/lint"}
    found, seen = paged(monkeypatch, "FAILURE", [passing, [rspec, *passing[:99]], [lint]])
    assert found == [{"name": "rspec", "url": "https://ci/rspec"}, {"name": "lint", "url": "https://ci/lint"}], \
        "a failed rollup with over 100 checks asks for the next pages until it has named every failed check"
    assert len(seen) == 3, "each page past the first is one more graphql call"
    assert all('repository(owner: "acme", name: "billing-reconciliation-service")' in q and "pullRequest(number: 2)" in q for q in seen[1:]), \
        "the next pages ask for the pr's own head commit"
    assert ['after: "c1"' in seen[1], 'after: "c2"' in seen[2]] == [True, True], "each page starts after the last one"


@pytest.mark.parametrize("ci", ["SUCCESS", "PENDING"])
def test_a_rollup_that_did_not_fail_asks_for_no_more_checks(monkeypatch, ci):
    found, seen = paged(monkeypatch, ci, [[{"name": "lint", "conclusion": "SUCCESS", "detailsUrl": None}], []])
    assert (found, len(seen)) == ([], 1), "a rollup that did not fail has no failed check to look for past the first 100"


def test_a_head_pushed_since_the_first_page_ends_the_pages(monkeypatch):
    rspec = {"name": "rspec", "conclusion": "FAILURE", "detailsUrl": "https://ci/rspec"}
    found, seen = paged(monkeypatch, "FAILURE", [[rspec], None])
    assert (found, len(seen)) == ([{"name": "rspec", "url": "https://ci/rspec"}], 2), \
        "a head pushed since the first page, with no checks yet, ends the pages with the failed checks found so far"


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
        "pr fetch asks for the check rollup of the head commit only, leaving its failed checks to their own query"
    assert all(pr.failed_checks == [] for pr in many), "pr fetch leaves the failed checks to their own query"
    node = pr_node(5, None)["pullRequest"]
    ghost = {**node, "author": None, "reviews": {"nodes": [{**CHANGES, "author": None}]},
             "reviewThreads": {"nodes": [{**THREAD, "comments": {"nodes": [{**THREAD["comments"][0], "author": None}]}}]}}
    pr = github.pr_from_graph(ghost, "acme/app")
    assert pr.author == {"login": "ghost"}, "a deleted account reads as ghost"
    assert pr.reviews[0]["author"] == {"login": "ghost"}, "a deleted account reads as ghost"
    assert pr.threads[0]["comments"][0]["author"] == {"login": "ghost"}, "a deleted account reads as ghost"
    assert all(re.search(rf"\b{name}\b", query) for name in ("login", "body", "createdAt", "diffHunk", "url")), \
        "pr fetch asks for every comment field the popup shows"
