import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from textual.content import Content
from textual.widgets import Input, OptionList, Static

from tarkon import board as board_module
from tarkon import app as app_module
from tarkon import config, fetch, web
from tarkon.app import TarkonApp

board_module.TUI_REPO_ALIASES["billing-reconciliation-service"] = "brs"

PR_ONE = {"url": "https://github.com/acme/app/pull/1", "repo": "app", "number": 1, "title": "[ACME-1] First change",
          "author": {"login": "alice"}, "isDraft": False, "reviewDecision": "", "reviews": [], "reviewRequests": [{}],
          "createdAt": "2026-10-20T10:00:00Z", "ci": "failing", "mergeable": "CONFLICTING", "headRefName": "ACME-1-x",
          "commits": [{"committedDate": "2026-10-21T10:00:00Z"}]}
PR_TWO = {"url": "https://github.com/acme/billing-reconciliation-service/pull/2", "repo": "billing-reconciliation-service",
          "number": 2, "title": "[ACME-2] Second change", "author": {"login": "bob"}, "isDraft": False, "reviewDecision": "APPROVED",
          "reviews": [{"submittedAt": "2026-10-22T09:00:00Z", "state": "APPROVED", "author": {"login": "alice"}}], "reviewRequests": [],
          "createdAt": "2026-10-21T10:00:00Z", "ci": "passing", "mergeable": "MERGEABLE", "headRefName": "ACME-2-y", "commits": []}
PR_THREE = {**PR_ONE, "url": "https://github.com/acme/app/pull/3", "number": 3, "title": "[ACME-3] Third change",
            "createdAt": "2026-10-23T10:00:00Z"}
TICKETS = [{"key": "ACME-1", "summary": "Ticket one", "status": "En proceso", "column": "doing", "assignee": "Ana", "updated": None, "prs": []},
           {"key": "ACME-2", "summary": "Ticket two", "status": "Finalizado", "column": "done", "assignee": "Ana", "updated": None, "prs": []}]
LINK = '<a href="https://github.com/acme/app/pull/1" title="app#1">[ACME-1]</a> First change'


def board(prs):
    return {"epics": [{"key": "ACME-100", "summary": "Epic one", "status": "Developing", "owner": "Ana"}],
            "tickets_by_epic": {"ACME-100": TICKETS}, "by_key": {t["key"]: t for t in TICKETS}, "prs": prs, "review_prs": [],
            "my_prs": [PR_ONE], "my_tickets": [{"key": "ACME-1", "summary": "Ticket one", "status": "En proceso", "days_in_status": 2}],
            "attention": [(LINK, "Open for review, but the ticket is still In progress. Move it to In review?")],
            "changes": [{"at": "2026-10-24T02:04", "tone": "commented", "label": "New PR", "text": LINK, "item": PR_ONE["url"]}],
            "out": Path("board.html")}


SETTINGS = {"team": ["alice", "bob"], "jira_project": "ACME", "github_user": "alice", "github_org": "acme",
            "jira_url": "https://acme.atlassian.net"}

results = []


def settings_file(cache, settings=SETTINGS):
    path = cache.with_name("config.json")
    path.write_text(json.dumps(settings))
    return path


def check(name, ok):
    results.append(ok)
    print("PASS" if ok else "FAIL", name)


async def main(cache):
    boards = [board([PR_ONE, PR_TWO]), board([PR_ONE, PR_TWO, PR_THREE])]
    opened, copied, now = [], [], [1000.0]
    app = TarkonApp(load=lambda: boards.pop(0), opener=opened.append, copier=copied.append, clock=lambda: now[0], cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        detail = lambda: str(app.query_one("#detail", Static).render())
        title = lambda key: str(app.query_one(f"#panel-{key}").border_title)
        focused = lambda key: app.focused is app.query_one(f"#list-{key}")
        check("there is no tab bar", not app.query("TabbedContent"))
        status = app.query_one("#status", Static)
        check("updated time uses the brand color", str(status.render()).startswith("updated")
              and status.styles.color == app.query_one(".brand").styles.color)
        check("there is no my desk or worktrees box", not app.query("#panel-desk") and not app.query("#panel-worktrees"))
        titles = [str(panel.border_title) for panel in app.query(".panel")]
        check("overview numbers its boxes next to details",
              titles == ["[1] attention 1", "[2] team prs 2", "[3] changes 1", "[4] epics 1", "details"])
        check("overview starts on the attention box", "Move it to In review?" in detail())
        heights = {key: app.query_one(f"#panel-{key}").outer_size.height for key in ("attention", "prs", "changes", "epics")}
        check("attention box fits its items", heights["attention"] == 5)
        check("epics box fits its items", heights["epics"] == 5)
        check("team prs and changes share the rest", abs(heights["prs"] - heights["changes"]) <= 1 and heights["prs"] > 5)
        await pilot.click("#list-prs", offset=(2, 1))
        check("click in the team prs box shows that PR", "Second change" in detail())
        await pilot.click("#list-changes", offset=(2, 0))
        check("click in the changes box shows that change", "New PR" in detail())
        await pilot.press("enter")
        check("enter opens the item of the focused box", opened == [PR_ONE["url"]])
        opened.clear()
        await pilot.press("2")
        check("2 focuses the team prs box", focused("prs") and "Second change" in detail())
        await pilot.press("k")
        check("k moves up, detail keeps the ticket prefix", "[ACME-1] First change" in detail())
        await pilot.press("j")
        check("j moves to next PR", "Second change" in detail())
        bar = app.query_one("#list-epics", OptionList).get_option_at_index(0).prompt
        segments = [(bar.plain[s.start:s.end], str(s.style)) for s in bar.spans if bar.plain[s.start] in "█░"]
        check("epic progress is a block bar", "█" * 10 + "░" * 10 in bar.plain)
        check("done blocks are green and the rest dim", segments == [("█" * 10, "#56d364"), ("░" * 10, "#6e7a87")])
        check("long repo shown as alias", "brs#2" in str(app.query_one("#list-prs", OptionList).get_option_at_index(1).prompt))
        await pilot.press("enter")
        check("enter opens the PR", opened == [PR_TWO["url"]])
        await pilot.click("#list-prs", offset=(2, 0))
        check("click on a row selects it", "First change" in detail())
        await pilot.click("#detail", offset=(10, 2))
        check("click on a detail link opens it", opened[-1] == PR_ONE["url"])
        await pilot.press("slash")
        check("slash focuses the filter of the focused box", app.focused is app.query_one("#filter-prs"))
        await pilot.press(*"second")
        check("filter narrows the list", app.query_one("#list-prs", OptionList).option_count == 1)
        await pilot.press("escape")
        check("escape clears the filter", app.query_one("#list-prs", OptionList).option_count == 2 and focused("prs"))
        await pilot.press("1")
        check("1 focuses the attention box", focused("attention") and "Move it to In review?" in detail())
        await pilot.press("4")
        check("4 focuses the epics box", focused("epics") and "Epic one" in detail())
        await pilot.press("3")
        check("3 focuses the changes box", focused("changes"))
        await pilot.press("4")
        await pilot.press("y")
        check("y copies the epic key", copied == ["ACME-100"])
        now[0] += 30
        await pilot.press("r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("refresh within a minute is skipped", title("prs") == "[2] team prs 2")
        check("skipped refresh says when the next one is allowed", any("next refresh in 30s" in n.message for n in app._notifications))
        now[0] += 31
        await pilot.press("r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("refresh reloads the board", title("prs") == "[2] team prs 3")
        check("refresh keeps the focused box", focused("epics"))


def failing_load():
    raise subprocess.CalledProcessError(1, ["gh", "search", "prs", "--json", "number"], stderr="API rate limit exceeded\n")


async def reopen(cache):
    calls = []
    def load():
        calls.append(1)
        return board([PR_ONE, PR_TWO, PR_THREE])
    cache.write_text(json.dumps({"at": 1000.0, "board": board([PR_ONE])}, default=str))
    app = TarkonApp(load=load, opener=print, copier=print, clock=lambda: 1030.0, cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("reopening within a minute does not refresh", calls == [])
        check("reopening within a minute shows the saved board", str(app.query_one("#panel-prs").border_title) == "[2] team prs 1")
    app = TarkonApp(load=load, opener=print, copier=print, clock=lambda: 1090.0, cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("reopening after a minute refreshes once", calls == [1])
        check("refreshed board replaces the saved one", str(app.query_one("#panel-prs").border_title) == "[2] team prs 3")
        check("successful refresh saves the board", json.loads(cache.read_text())["at"] == 1090.0)


async def running(cache):
    release, calls = threading.Event(), []
    def slow_load():
        calls.append(1)
        release.wait(5)
        return board([PR_ONE])
    now = [1000.0]
    app = TarkonApp(load=slow_load, opener=print, copier=print, clock=lambda: now[0], cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        now[0] += 120
        await pilot.press("r")
        await pilot.pause()
        check("refresh while one is running is skipped", any("refresh already running" in n.message for n in app._notifications))
        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("only one load ran", len(calls) == 1)


async def failure(cache):
    app = TarkonApp(load=failing_load, opener=print, copier=print, cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("failed refresh keeps the app running", app.is_running)
        check("failed refresh shows the command error", any("API rate limit exceeded" in n.message for n in app._notifications))
        check("failed refresh saves nothing", not cache.exists())


async def first_run(cache):
    cache = cache.parent / "missing" / "cache.json"
    path, calls = cache.with_name("config.json"), []
    def load():
        calls.append(1)
        return board([PR_ONE])
    app = TarkonApp(load=load, opener=print, copier=print, cache=cache, config_path=path)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        inputs = {i.id.removeprefix("config-"): i for i in app.screen.query(Input)}
        check("first run opens the config panel with the five fields", sorted(inputs) == sorted(SETTINGS))
        check("config fields start empty with a placeholder", all(not i.value and i.placeholder for i in inputs.values()))
        check("board waits until the config is saved", calls == [])
        check("config panel hides the board keys and cancel on first run",
              not app.check_action("focus_filter", ()) and not app.check_action("refresh", ())
              and not app.screen.check_action("cancel", ()) and app.screen.check_action("save", ()))
        inputs["team"].value = "alice, bob"
        await pilot.click("#config-save")
        await pilot.pause()
        check("saving with empty fields is refused", not path.exists()
              and any("Fill in every field" in n.message for n in app._notifications))
        for key, value in {"jira_project": "ACME", "github_user": "alice", "github_org": "acme",
                           "jira_url": "https://acme.atlassian.net"}.items():
            inputs[key].value = value
        await pilot.pause(0.3)
        await pilot.click("#config-save")
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("saving writes the config", json.loads(path.read_text()) == SETTINGS)
        check("saving opens the board", calls == [1] and str(app.query_one("#panel-prs").border_title) == "[2] team prs 1")
        check("the TUI cache is written into a folder created on demand", cache.exists())


async def edit(cache):
    path = settings_file(cache)
    app = TarkonApp(load=lambda: board([PR_ONE]), opener=print, copier=print, cache=cache, config_path=path, edit_config=True)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        inputs = {i.id.removeprefix("config-"): i for i in app.screen.query(Input)}
        check("config command can be cancelled", app.screen.check_action("cancel", ()))
        check("config command shows the saved values", inputs["team"].value == "alice, bob" and inputs["jira_project"].value == "ACME")
        inputs["team"].value = "alice bob, carol"
        await pilot.click("#config-save")
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("config command saves the changes", json.loads(path.read_text())["team"] == ["alice", "bob", "carol"])
        check("config command then opens the board", str(app.query_one("#panel-prs").border_title) == "[2] team prs 1")


def settings_used():
    config.use(config.Settings(team=["alice"], jira_project="ACME", github_user="me", github_org="acme",
                               jira_url="https://acme.atlassian.net/"))
    check("jira links use the configured site", 'href="https://acme.atlassian.net/browse/ACME-9"' in board_module.jira_link("ACME-9"))
    seen, run_json = [], fetch.run_json
    fetch.run_json = lambda cmd: seen.append(cmd) or []
    try:
        fetch.search_team_prs()
    finally:
        fetch.run_json = run_json
    check("team PR search uses the configured users and org", len(seen) == 1 and "alice" in seen[0] and "acme" in seen[0])
    seen.clear()
    items = [{"key": "ACME-9", "fields": {"summary": "Newer", "status": {"name": "Rollout"}, "assignee": None}},
             {"key": "ACME-2", "fields": {"summary": "Older", "status": {"name": "Developing"},
                                          "assignee": {"displayName": "Ana"}}}]
    fetch.run_json = lambda cmd: seen.append(cmd) or items
    try:
        epics = fetch.fetch_epics()
    finally:
        fetch.run_json = run_json
    jql = seen[0][seen[0].index("--jql") + 1]
    check("epics come from the configured project in Developing or Rollout, newest first",
          jql == 'project = ACME AND issuetype = Epic AND status in ("Developing", "Rollout") ORDER BY created DESC')
    check("fetched epics keep Jira's order", epics == [
        {"key": "ACME-9", "summary": "Newer", "status": "Rollout", "owner": "Unassigned"},
        {"key": "ACME-2", "summary": "Older", "status": "Developing", "owner": "Ana"}])


def epic_changes():
    epic_one, epic_two = {"key": "ACME-100", "summary": "Epic one"}, {"key": "ACME-200", "summary": "Epic two"}
    one, two, three = ({"key": key, "summary": f"Ticket {key}", "status": "En proceso"} for key in ("ACME-1", "ACME-2", "ACME-3"))
    summaries = {t["key"]: t["summary"] for t in (one, two, three)}
    pr = {**PR_TWO, "headRefOid": "abc"}
    before = board_module.snapshot([epic_one], {"ACME-100": [one]}, [])
    now = board_module.snapshot([epic_one, epic_two], {"ACME-100": [one], "ACME-200": [two, three]}, [pr])
    found = board_module.changes_between(before, now, summaries)
    check("a new epic is one change with its summary", [(c["label"], c["item"]) for c in found]
          == [("New epic", "https://acme.atlassian.net/browse/ACME-200")] and "Epic two" in found[0]["text"])
    run_json = board_module.run_json
    board_module.run_json = lambda cmd: (_ for _ in ()).throw(AssertionError(cmd))
    try:
        found = board_module.changes_between(now, before, summaries)
    finally:
        board_module.run_json = run_json
    check("an epic leaving is one change, without per-ticket or PR lookups",
          [(c["label"], c["item"]) for c in found] == [("Off the epics", "https://acme.atlassian.net/browse/ACME-200")])
    grown = board_module.snapshot([epic_one], {"ACME-100": [one, two]}, [])
    found = board_module.changes_between(before, grown, summaries)
    check("a new ticket in a known epic still joins the epics", [c["label"] for c in found] == ["En proceso"]
          and "joins the epics" in found[0]["text"])
    legacy = {key: value for key, value in before.items() if key != "epics"}
    found = board_module.changes_between(legacy, grown, summaries)
    check("a saved state without epics still reports new tickets", [c["label"] for c in found] == ["En proceso"])


def data_paths():
    home = Path.home()
    check("state lives in ~/.local/state/tarkon", board_module.STATE_PATH == home / ".local/state/tarkon/state.json")
    check("the html page lives next to the state", web.OUT == home / ".local/state/tarkon/board.html")
    check("the TUI cache lives in ~/.cache/tarkon", app_module.CACHE == home / ".cache/tarkon/cache.json")
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "missing" / "board.html"
        found = {**board([PR_ONE]), "merged_by_ticket": {}, "now": {"prs": {}}}
        collect, path = web.collect, web.OUT
        web.collect, web.OUT = lambda: found, out
        try:
            result = web.build()
        finally:
            web.collect, web.OUT = collect, path
        check("the html page is written into a folder created on demand", out.exists() and result["out"] == out)
        page = out.read_text().lower()
        check("the html page has no worktrees or herdr", "worktree" not in page and "herdr" not in page)
    check("nothing scans ~/projects or calls herdr", not hasattr(fetch, "fetch_worktrees") and not hasattr(fetch, "herdr_workspaces"))


def missing_tools():
    for args in ([], ["html"]):
        try:
            result = subprocess.run([sys.executable, "-m", "tarkon", *args], capture_output=True, text=True,
                                    cwd=Path(__file__).parent, env={**os.environ, "PATH": "/usr/bin:/bin"}, timeout=15)
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess(args, None, "", "timed out")
        check(f"missing gh and acli are explained before {' '.join(args) or 'the TUI'} starts",
              result.returncode == 1 and "gh not found" in result.stderr and "brew install gh" in result.stderr
              and "acli not found" in result.stderr and "brew install acli" in result.stderr and "Traceback" not in result.stderr)


def escaping():
    check("tui links keep a title ending in a backslash",
          Content.from_markup(app_module.link("https://github.com/acme/app/pull/1", "Fix path\\")).plain.rstrip(app_module.ZERO_WIDTH_SPACE)
          == "Fix path\\")
    config.use(config.Settings(team=["alice"], jira_project="ACME", github_user="me", github_org="acme",
                               jira_url='https://acme.atlassian.net/"><b>site</b>'))
    epic = {"key": "ACME-100", "summary": "Epic one", "status": "Developing", "owner": "Ana"}
    rendered = (board_module.jira_link("ACME-9<i>") + web.tui_epic(epic, TICKETS)["detail"]
                + web.tui_ticket({**TICKETS[0], "days_in_status": 2}, [])["detail"])
    check("jira links escape the site and the key", "<b>" not in rendered and "<i>" not in rendered)


def html_without_config():
    with tempfile.TemporaryDirectory() as home:
        result = subprocess.run([sys.executable, "-m", "tarkon", "html"], capture_output=True, text=True,
                                cwd=Path(__file__).parent, env={**os.environ, "HOME": home})
    check("html without config asks to configure first",
          result.returncode == 1 and "Run `python -m tarkon config` first" in result.stderr)


if __name__ == "__main__":
    settings_used()
    escaping()
    config.use(config.Settings(**SETTINGS))
    epic_changes()
    data_paths()
    html_without_config()
    missing_tools()
    for test in (main, reopen, running, failure, first_run, edit):
        with tempfile.TemporaryDirectory() as scratch:
            asyncio.run(test(Path(scratch) / "cache.json"))
    sys.exit(0 if all(results) else 1)
