import asyncio
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from textual.content import Content
from textual.widgets import Input, OptionList, Static
from PIL import Image as PILImage
from textual_image._geometry import CellSize
from textual_image.widget import Image, get_cell_size

from tarkon import board as board_module
from tarkon import app as app_module
from tarkon import config, fetch, web
from tarkon.app import TarkonApp

board_module.TUI_REPO_ALIASES["billing-reconciliation-service"] = "brs"

PR_ONE = {"url": "https://github.com/acme/app/pull/1", "repo": "app", "number": 1, "title": "[ACME-1] First change",
          "author": {"login": "alice"}, "isDraft": False, "reviewDecision": "", "reviews": [], "reviewRequests": [{}],
          "createdAt": "2026-10-20T10:00:00Z", "ci": "failing", "mergeable": "CONFLICTING", "headRefName": "ACME-1-x",
          "commits": [{"committedDate": "2026-10-21T10:00:00Z"}], "threads": []}
PR_TWO = {"url": "https://github.com/acme/billing-reconciliation-service/pull/2", "repo": "billing-reconciliation-service",
          "number": 2, "title": "[ACME-2] Second change", "author": {"login": "bob"}, "isDraft": False, "reviewDecision": "APPROVED",
          "reviews": [{"submittedAt": "2026-10-22T09:00:00Z", "state": "APPROVED", "body": "", "author": {"login": "alice"}}], "reviewRequests": [],
          "createdAt": "2026-10-21T10:00:00Z", "ci": "passing", "mergeable": "MERGEABLE", "headRefName": "ACME-2-y", "commits": [], "threads": []}
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
        check("the header shows the logo instead of the rocket", isinstance(app.query_one("#top #logo"), Image)
              and "🚀" not in str(app.query_one("#top .brand").render()) and app.query_one("#top").outer_size.height == 1)
        logo, cell = app.query_one("#logo"), get_cell_size()
        width, height = PILImage.open(app_module.LOGO).size
        check("the title reads Tarkon", str(app.query_one("#top .brand").render()).strip() == "Tarkon")
        check("the boxes start one row below the header",
              app.query_one("#panel-attention").region.y >= app.query_one("#top").region.bottom + 1)
        check("the logo keeps its proportions", abs(logo.size.width - logo.size.height * cell.height * width / height / cell.width) <= 1)
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


async def throttle_across_runs(cache):
    calls = []
    def load():
        calls.append(1)
        return board([PR_ONE])
    app = TarkonApp(load=failing_load, opener=print, copier=print, clock=lambda: 1000.0, cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
    app = TarkonApp(load=load, opener=print, copier=print, clock=lambda: 1030.0, cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("reopening within a minute of a failed refresh does not refresh", calls == [])
        check("an empty board says when it will refresh", "next refresh in 30s" in str(app.query_one("#status", Static).render()))
        await pilot.press("r")
        await pilot.pause()
        check("r within a minute of a refresh in an earlier run is skipped",
              calls == [] and any("next refresh in 30s" in n.message for n in app._notifications))
    app = TarkonApp(load=load, opener=print, copier=print, clock=lambda: 1061.0, cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        check("reopening after the minute refreshes", calls == [1])


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
        check("the config panel shows the logo instead of the rocket", isinstance(app.screen.query_one("#logo"), Image)
              and all("🚀" not in str(brand.render()) for brand in app.screen.query(".brand")))
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


HUNK = "@@ -1,5 +1,5 @@\n def total\n   items\n-    .sum(&:price)\n+    .sum { |item| item.price * item.qty }\n end"
THREAD = {"isResolved": False, "isOutdated": False, "path": "app/models/order.rb", "line": 12,
          "comments": [{"author": {"login": "carol"}, "body": "Rename qty to quantity", "createdAt": "2026-10-22T09:05:00Z", "diffHunk": HUNK,
                        "url": "https://github.com/acme/app/pull/2#discussion_r1"},
                       {"author": {"login": "bob"}, "body": "Done", "createdAt": "2026-10-22T10:00:00Z", "diffHunk": HUNK,
                        "url": "https://github.com/acme/app/pull/2#discussion_r2"}]}
OUTDATED = {"isResolved": False, "isOutdated": True, "path": "README.md", "line": None,
            "comments": [{"author": {"login": "alice"}, "body": "Typo", "createdAt": "2026-10-22T11:00:00Z",
                          "diffHunk": "@@ -1,2 +1,2 @@\n # App\n-Teh app", "url": "https://github.com/acme/app/pull/2#discussion_r3"}]}
NOTE = {"author": {"__typename": "User", "login": "alice"}, "body": "Nice work, this reads well", "createdAt": "2026-10-22T08:00:00Z",
        "url": "https://github.com/acme/app/pull/2#issuecomment-1"}
REPLY = {**NOTE, "author": {"__typename": "User", "login": "bob"}, "body": "Thanks!", "createdAt": "2026-10-22T09:30:00Z",
         "url": "https://github.com/acme/app/pull/2#issuecomment-2"}
CHANGES = {"submittedAt": "2026-10-22T09:00:00Z", "state": "CHANGES_REQUESTED", "body": "Please split this", "author": {"login": "carol"}}


def pr_rows():
    row = lambda pr: app_module.cell_row(app_module.pr_entry(pr, {}), app_module.PR_WIDTHS).plain
    check("team pr row shows the title's ticket code and the author", "[ACME-1]" in row(PR_ONE) and "alice" in row(PR_ONE))
    check("team pr row without a ticket code shows no code", "[" not in row({**PR_ONE, "title": "No ticket"})
          and "alice" in row({**PR_ONE, "title": "No ticket"}))


def pr_comments():
    review = {"submittedAt": "2026-10-22T09:00:00Z", "state": "CHANGES_REQUESTED", "body": "Please split this", "author": {"login": "carol"}}
    pr = {**PR_TWO, "reviews": [*PR_TWO["reviews"], review], "commits": [{"committedDate": "2026-10-23T08:00:00Z"}], "threads": [THREAD]}
    detail = Content.from_markup(app_module.pr_entry(pr, {}).detail).plain
    check("pr detail counts the comments and says how to open them", "comments 2 · c to open" in detail)
    check("pr detail leaves the comments themselves to the popup", all(text not in detail for text in
          ("Please split this", "app/models/order.rb", ".sum { |item|", "Rename qty to quantity")))
    activity = detail[detail.index("── activity ──"):]
    check("activity is newest first", activity.index("commit") < activity.index("approved"))
    check("pr detail without comments has no comments line", "comments" not in Content.from_markup(app_module.pr_entry(PR_ONE, {}).detail).plain)


def conversation_comments():
    pr = {**PR_TWO, "reviews": [CHANGES], "threads": [THREAD], "conversation": [NOTE, REPLY]}
    items = app_module.review_items(pr)
    check("conversation comments sit with the reviews by date, before the code threads",
          [str(item["row"]).splitlines()[0] for item in items] == ["comment", "changes requested", "comment", "order.rb:12"])
    check("a conversation comment shows its author and text", str(items[0]["row"]).splitlines()[1:] == ["alice", "Nice work, this reads well"]
          and "alice commented" in Content.from_markup(items[0]["place"]).plain
          and "Nice work, this reads well" in Content.from_markup("\n".join(items[0]["comments"])).plain)
    check("enter on a conversation comment opens that comment", items[0]["url"] == NOTE["url"])
    check("the detail counts conversation comments too",
          "comments 4 · c to open" in Content.from_markup(app_module.pr_entry(pr, {}).detail).plain)


def diff_rendering():
    diff = app_module.diff_text(HUNK, "app/models/order.rb")
    lines = diff.plain.splitlines()
    check("diff keeps the hunk header", lines[0].strip() == "@@ -1,5 +1,5 @@")
    check("diff numbers context lines on both sides", re.match(r"\s*1\s+1\s+def total", lines[1]) is not None)
    check("diff numbers a removed line on the old side", re.match(r"\s*3\s+-\s+\.sum\(&:price\)", lines[3]) is not None)
    check("diff numbers an added line on the new side", re.match(r"\s*3\s+\+\s+\.sum \{", lines[4]) is not None)
    check("the line numbers take only the width they need", lines[1].startswith("1 1  def total")
          and lines[4].startswith("  3 +    .sum {") and lines[0] == "    @@ -1,5 +1,5 @@")
    added_only = app_module.diff_text("@@ -0,0 +1,2 @@\n+first\n+second", "notes.md").plain.splitlines()
    check("a hunk of only additions shows a single number column", [line.rstrip() for line in added_only[1:]] == ["1 +first", "2 +second"]
          and added_only[0] == "  @@ -0,0 +1,2 @@")
    added = diff.plain.index("+    .sum {")
    check("added lines have a green background, removed ones red",
          any(span.start <= added < span.end and str(span.style).endswith(f"on {app_module.DIFF_BACKGROUNDS['+']}") for span in diff.spans)
          and app_module.DIFF_BACKGROUNDS["+"] != app_module.DIFF_BACKGROUNDS["-"])


async def review_popup(cache):
    pr_two = {**PR_TWO, "reviews": [*PR_TWO["reviews"], CHANGES], "threads": [THREAD, OUTDATED]}
    opened, copied = [], []
    app = TarkonApp(load=lambda: board([PR_ONE, pr_two]), opener=opened.append, copier=copied.append, clock=lambda: 1000.0,
                         cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = lambda selector: str(app.screen.query_one(selector, Static).render())
        await pilot.press("2", "j", "c")
        check("c opens the review comments of the selected PR", isinstance(app.screen, app_module.ReviewScreen))
        check("the popup lists the review and every open thread", app.screen.query_one(OptionList).option_count == 3)
        check("the popup title names the PR", "brs#2" in str(app.screen.query_one("#review").border_title))
        prompts = [str(app.screen.query_one(OptionList).get_option_at_index(i).prompt) for i in range(3)]
        check("each thread in the list previews its first comment", "Please split this" in prompts[0]
              and "Rename qty to quantity" in prompts[1] and "Typo" in prompts[2])
        check("each thread shows file, author and description on their own lines",
              prompts[1].splitlines() == ["order.rb:12", "carol · 2 comments", "Rename qty to quantity"]
              and prompts[0].splitlines() == ["changes requested", "carol", "Please split this"])
        check("an outdated thread says so in the list", prompts[2].splitlines()[0] == "README.md · outdated")
        check("the popup footer explains how to move", any(b.key_display == "j/k" for b in app.screen.query_one(OptionList)._bindings
                                                                                       .key_to_bindings.get("j", [])))
        check("a review shows its body without a diff", "Please split this" in text("#review-comments")
              and not app.screen.query_one("#review-diff-box").display)
        await pilot.press("j")
        check("j moves to the next thread and shows its file and line", "app/models/order.rb:12" in text("#review-place"))
        check("the thread shows its diff", app.screen.query_one("#review-diff-box").display and ".sum { |item|" in text("#review-diff"))
        check("the thread shows every comment in order", text("#review-comments").index("Rename qty") < text("#review-comments").index("Done"))
        await pilot.press("enter")
        check("enter opens the thread on GitHub", opened[-1] == THREAD["comments"][0]["url"])
        await pilot.press("y")
        check("y copies the thread link", copied[-1] == THREAD["comments"][0]["url"])
        await pilot.press("j")
        check("an outdated thread says so", "outdated" in text("#review-place") and "README.md" in text("#review-place"))
        await pilot.press("q")
        check("q closes the popup without quitting", not isinstance(app.screen, app_module.ReviewScreen) and app.is_running)
        await pilot.press("k", "c")
        check("c on a PR without comments keeps the board", not isinstance(app.screen, app_module.ReviewScreen))
        await pilot.press("j")
        detail = str(app.query_one("#detail", Static).render()).splitlines()
        row = next(i for i, line in enumerate(detail) if "c to open" in line)
        await pilot.click("#detail", offset=(10, row))
        check("clicking the comments line in the detail opens the popup", isinstance(app.screen, app_module.ReviewScreen))
        await pilot.press("escape")
        check("escape closes the popup", not isinstance(app.screen, app_module.ReviewScreen))


def pr_threads_fetch():
    resolved = {**THREAD, "isResolved": True, "path": "app/old.rb"}
    nodes = [{**t, "comments": {"nodes": t["comments"]}} for t in (THREAD, resolved)]
    bots = [{**NOTE, "author": {"__typename": "Bot", "login": "github-actions"}}, {**NOTE, "author": {"__typename": "User", "login": "deploybot"}}]
    graph = {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": nodes}, "comments": {"nodes": [*bots, NOTE]}}}}}
    seen, run_json, fetch_ci = [], fetch.run_json, fetch.fetch_ci
    fetch.run_json = lambda cmd: seen.append(cmd) or (graph if "graphql" in cmd else {"number": 2, "title": "x"})
    fetch.fetch_ci = lambda repo, number: "passing"
    try:
        pr = fetch.fetch_pr("acme/app", 2)
    finally:
        fetch.run_json, fetch.fetch_ci = run_json, fetch_ci
    check("pr fetch keeps only unresolved review threads", pr["threads"] == [THREAD])
    check("pr fetch keeps conversation comments from people, not bots", pr["conversation"] == [NOTE])
    check("pr fetch asks for the threads of that pr", any("graphql" in cmd and "owner=acme" in cmd and "name=app" in cmd and "number=2" in cmd
                                                          for cmd in seen))
    query = next(arg for cmd in seen if "graphql" in cmd for arg in cmd if arg.startswith("query="))
    check("pr fetch asks for every comment field the popup shows",
          all(re.search(rf"\b{name}\b", query) for name in ("login", "body", "createdAt", "diffHunk", "url")))


def logo_fit():
    source = PILImage.open(app_module.LOGO)
    for cell in (CellSize(8, 17), CellSize(10, 20), CellSize(9, 21)):
        image, columns = app_module.logo_image(2, cell)
        box = columns * cell.width / (2 * cell.height)
        check(f"logo fills a whole {columns}x2 box of {cell.width}x{cell.height} cells without stretching",
              abs(image.width / image.height - box) < 0.02 and image.height == source.height and image.width >= source.width)


def html_logo():
    with tempfile.TemporaryDirectory() as scratch:
        found = {**board([PR_ONE]), "merged_by_ticket": {}, "now": {"prs": {}}}
        collect, path = web.collect, web.OUT
        web.collect, web.OUT = lambda: found, Path(scratch) / "board.html"
        try:
            page = web.build()["out"].read_text()
        finally:
            web.collect, web.OUT = collect, path
    logo = "data:image/png;base64," + base64.b64encode(Path(web.__file__).with_name("logo.png").read_bytes()).decode()
    check("html favicon is the logo", f'<link rel="icon" type="image/png" href="{logo}">' in page)
    check("html headers show the logo instead of the rocket", page.count(f'src="{logo}"') == 2 and "rotate(45 16 16)" not in page)


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
    pr_rows()
    pr_comments()
    pr_threads_fetch()
    conversation_comments()
    diff_rendering()
    data_paths()
    logo_fit()
    html_logo()
    html_without_config()
    missing_tools()
    for test in (main, reopen, throttle_across_runs, running, failure, first_run, edit, review_popup):
        with tempfile.TemporaryDirectory() as scratch:
            asyncio.run(test(Path(scratch) / "cache.json"))
    sys.exit(0 if all(results) else 1)
