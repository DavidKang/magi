import datetime as dt
from dataclasses import replace

from textual.content import Content

from builders import CHANGES, NOTE, OUTDATED, PR_ONE, PR_TWO, REPLY, STATED, SUBJECT, THREAD, TICKET_DETAIL, board
from magi.domain import review
from magi.domain.ages import days_since
from magi.domain.entities import Ticket
from magi.domain.factory import FactoryTicket
from magi.domain.status import status_label
from magi.tui import entries, theme


def test_ticket_detail():
    ticket = Ticket(key="ACME-1", summary="Ticket one", status="En proceso", detail=TICKET_DETAIL)
    detail = Content.from_markup(entries.ticket_entry(ticket, [], STATED).detail).plain
    assert "In Progress" in detail and "En proceso" not in detail, "my ticket detail names the status in English"
    assert all(text in detail for text in ["Story", "Low", "ACME-100", "Epic one", "Bob", "updated", "blocked"]), \
        "my ticket detail shows type, priority, epic, creator, last update and labels"
    assert "Oct 08" not in detail, "my ticket detail leaves out when the ticket was created"
    assert "Use the new reason column." in detail, "my ticket detail previews the description and counts the comments"
    assert "comments 1 · c to open" in detail, "my ticket detail previews the description and counts the comments"


def test_ticket_detail_lists_its_prs_with_their_review_in_colour():
    days = lambda n: (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=n)).isoformat()
    first, other = replace(PR_ONE, created_at=days(3)), replace(PR_TWO, title="[ACME-1] Second change", created_at=days(1))
    ticket = Ticket(key="ACME-1", summary="Ticket one", status="En proceso", detail=TICKET_DETAIL)
    detail = entries.ticket_entry(ticket, [first, other], STATED).detail
    lines = Content.from_markup(detail).plain.splitlines()
    start = lines.index("── prs (2) ──")
    refs = ["app#1".ljust(32), "billing-reconciliation-service#2"]
    assert lines[start + 1:start + 3] == [f"• {refs[0]}  Awaiting review  alice · 3d", f"• {refs[1]}  {'Approved'.ljust(15)}  bob · 1d"], \
        "a ticket's prs are a list, one per line, with their review state and who opened them"
    assert entries.colored("ok", "Approved") in detail and entries.colored("warn", "Awaiting review") in detail, \
        "each pr's review state reads in its colour"


def test_ticket_detail_without_prs_has_no_prs_section():
    lines = Content.from_markup(entries.ticket_entry(Ticket(key="ACME-1", summary="One", status="En proceso", detail=TICKET_DETAIL),
                                                     [], STATED).detail).plain.splitlines()
    assert not any(line.startswith("── prs") for line in lines), "a ticket without prs shows no prs section"


LABELLED = replace(TICKET_DETAIL, labels=["blocked", "fraud"])


def test_ticket_detail_colours_its_status_as_the_changes_feed_does():
    for status, tone in (("Tareas por hacer", "dim"), ("En proceso", "warn"), ("En revisión", "blue"), ("Ready To Deploy", "ok"),
                         ("Finalizado", "ok"), ("Rejected / Cancelled", "fg")):
        detail = entries.ticket_entry(Ticket(key="ACME-1", summary="One", status=status, detail=TICKET_DETAIL), [], STATED).detail
        assert entries.colored(tone, status_label(status)) in detail, \
            f"a ticket {status!r} reads in its column's colour, as in the changes feed, and plain in no column"


def test_ticket_detail_colours_its_labels():
    detail = entries.ticket_entry(Ticket(key="ACME-1", summary="One", status="En proceso", detail=LABELLED), [], STATED).detail
    assert f"[b]{entries.muted('bad', 'blocked')}" not in detail and entries.muted("bad", "blocked") in detail \
        and entries.colored("warn", "fraud") in detail, "the blocked label reads in a muted red, the others as amber tags"


def test_ticket_detail_shows_its_labels_under_its_status():
    lines = Content.from_markup(entries.ticket_entry(Ticket(key="ACME-1", summary="One", status="En revisión", detail=LABELLED),
                                                     [], STATED).detail).plain.splitlines()
    status = lines.index("status   In review")
    assert lines[status - 1:status + 2] == ["ticket   ACME-1 · Story · Low", "status   In review", "labels   blocked · fraud"], \
        "a ticket's labels have their own line, under its status"


def test_detail_field_names_and_section_headers_stand_out():
    assert entries.field("ticket", "x").startswith(f"[{theme.COLORS['blue']}]"), "a detail's field names read in blue, not dimmed"
    assert entries.separator("links") == f"[b]{entries.muted('ok', '── links ──')}[/b]", "a detail's section headers read bold in a muted approved green"
    assert entries.muted("ok", "x") == "[#3C8F49]x[/]", "a muted tone is its colour a third of the way into the background"


def test_ticket_detail_edges():
    ticket = Ticket(key="ACME-1", summary="Ticket one", status="En proceso", detail=replace(
        TICKET_DETAIL, epic=None, comments=[], description="\n".join(f"line {n}" for n in range(1, 15))))
    lines = Content.from_markup(entries.ticket_entry(ticket, [], STATED).detail).plain.splitlines()
    assert "epic     —" in lines, "a ticket without an epic shows a dash"
    assert "labels   —" in Content.from_markup(entries.ticket_entry(Ticket(key="ACME-1", summary="One", status="En proceso", detail=replace(
        TICKET_DETAIL, labels=[])), [], STATED).detail).plain.splitlines(), "a ticket without labels shows a dash"
    assert "line 14" in lines, "a ticket's detail holds its whole description, for the details box to fit"
    long = entries.ticket_entry(ticket, [], STATED)
    folded = Content.from_markup(entries.folded(long.detail, long.fold, 5)).plain.splitlines()
    assert "line 5" in folded and "line 6" not in folded, "a folded description keeps the lines asked for"
    assert folded[-1] == "… c to read it all", "a folded description ends with a hint to open it"
    assert entries.colored("accent", entries.MORE_HINT) in entries.folded(long.detail, long.fold, 5), \
        "the hint to read the whole description reads in the accent colour of the section headers"
    assert entries.folded(long.detail, long.fold, 14) == long.detail, "a description that is kept whole has no hint"
    assert not any(line.startswith("comments") for line in lines), "a ticket without comments shows no comments line"
    cached = entries.ticket_entry(Ticket(key="OPS-7", summary="Ticket seven", status="Tareas por hacer"), [], STATED)
    assert cached.popup[1] == [], "a ticket cached before the detail fetch has nothing to open"
    shuffled = {**board([]), "my_tickets": [Ticket(key="A-1", summary="a", status="En proceso"),
                                            Ticket(key="A-2", summary="b", status="Tareas por hacer"),
                                            Ticket(key="A-3", summary="c", status="En proceso")]}
    assert [e.group for e in entries.entries(shuffled, STATED)["mine_tickets"]] == ["Todo", "In Progress", "In Progress"], \
        "my tickets from an older cache are regrouped by status"


CLEAR = replace(TICKET_DETAIL, labels=[])


ONE = Ticket(key="ACME-1", summary="Ticket one", status="En revisión", assignee="Ana", detail=CLEAR)


def test_a_kanban_row_tells_who_has_the_ticket_and_what_its_pr_misses():
    found = entries.entries({**board([PR_ONE]), "kanban": [ONE]}, STATED)["kanban"]
    missing = review.turn(PR_ONE)[1]
    assert found[0].cells == [("ACME-1", ""), ("", ""), ("Ana", "accent"), (missing, "blue-pill"),
                              (f"{days_since(CLEAR.updated)}d", "dim-right"), ("Ticket one", "")], \
        "a kanban row tells the ticket, who has it, mine in the accent colour, what its pr misses and the days since it last changed"


def test_a_kanban_ticket_without_a_pr_leaves_its_pr_cell_empty():
    seven = Ticket(key="ACME-7", summary="Ticket seven", status="Tareas por hacer", assignee="Luis", detail=CLEAR)
    found = entries.entries({**board([PR_ONE]), "kanban": [seven]}, STATED)["kanban"]
    assert found[0].cells[2:4] == [("Luis", "dim"), ("", "")], "a kanban ticket without a pr leaves its pr cell empty"


def test_a_kanban_ticket_shows_its_own_details():
    found = entries.entries({**board([PR_ONE]), "kanban": [ONE]}, STATED)["kanban"]
    assert found[0].detail == entries.ticket_entry(ONE, [PR_ONE], STATED).detail, "a kanban ticket's details are the ticket's own"


def test_a_kanban_row_tells_what_its_oldest_pr_misses():
    newer = replace(PR_TWO, title="[ACME-1] Follow-up")
    older = replace(PR_ONE, created_at="2026-10-19T10:00:00Z")
    found = entries.entries({**board([newer, older]), "kanban": [ONE]}, STATED)["kanban"]
    missing = review.turn(older)[1]
    assert found[0].cells[3] == (missing, "blue-pill"), "a kanban ticket with several prs tells what its oldest one misses"


def test_a_kanban_row_flags_a_ticket_labelled_blocked():
    kanban = [Ticket(key="ACME-1", summary="Ticket one", status="En proceso", assignee="Ana", detail=TICKET_DETAIL)]
    found = entries.entries({**board([]), "kanban": kanban}, STATED)["kanban"]
    assert found[0].cells[1] == ("blocked", "bad-pill"), "a kanban ticket with the blocked label says so in red"


def test_ticket_links():
    ticket = Ticket(key="ACME-1", summary="Ticket one", status="En proceso", detail=replace(
        TICKET_DETAIL, links=[*TICKET_DETAIL.links, {"relation": "relates to", "key": "ACME-3", "summary": "Third", "status": "Backlog"}]))
    lines = Content.from_markup(entries.ticket_entry(ticket, [], STATED).detail).plain.splitlines()
    start = lines.index("── links ──")
    assert lines[start + 1:start + 5] == ["• is blocked by ACME-2 (In review)", "  Ticket two", "• relates to ACME-3 (Backlog)", "  Third"], \
        "ticket links are a list, one item per link with its title below"
    assert not any(line.startswith("link ") for line in lines), "ticket links are a list, one item per link with its title below"


def test_escaping():
    assert (Content.from_markup(entries.link("https://github.com/acme/app/pull/1", "Fix path\\")).plain.rstrip(entries.ZERO_WIDTH_SPACE)
            == "Fix path\\"), "tui links keep a title ending in a backslash"


def test_pr_comments():
    review = {"submittedAt": "2026-10-22T09:00:00Z", "state": "CHANGES_REQUESTED", "body": "Please split this", "author": {"login": "carol"}}
    pr = replace(PR_TWO, reviews=[*PR_TWO.reviews, review], commits=[{"committedDate": "2026-10-23T08:00:00Z"}], threads=[THREAD])
    detail = Content.from_markup(entries.pr_entry(pr, {}, STATED).detail).plain
    assert "comments 2 · c to open" in detail, "pr detail counts the comments and says how to open them"
    assert (all(text not in detail for text in
            ("Please split this", "app/models/order.rb", ".sum { |item|", "Rename qty to quantity"))), \
        "pr detail leaves the comments themselves to the popup"
    activity = detail[detail.index("── activity ──"):]
    assert activity.index("commit") < activity.index("approved"), "activity is newest first"
    assert "comments" not in Content.from_markup(entries.pr_entry(PR_ONE, {}, STATED).detail).plain, \
        "pr detail without comments has no comments line"


def test_review_rows():
    items = entries.review_items(replace(PR_TWO, reviews=[*PR_TWO.reviews, CHANGES], threads=[THREAD, OUTDATED]))
    rows = [str(item["row"]).splitlines() for item in items]
    assert rows[0] == ["changes requested", "carol", "Please split this"], "each thread shows file, author and description on their own lines"
    assert rows[1] == ["order.rb:12", "carol · 2 comments", "Rename qty to quantity"], \
        "each thread shows file, author and description on their own lines"
    assert rows[2][0] == "README.md · outdated", "an outdated thread says so in the list"
    assert "Typo" in rows[2], "each thread in the list previews its first comment"


def test_conversation_comments():
    pr = replace(PR_TWO, reviews=[CHANGES], threads=[THREAD], conversation=[NOTE, REPLY])
    items = entries.review_items(pr)
    assert [str(item["row"]).splitlines()[0] for item in items] == ["comment", "changes requested", "comment", "order.rb:12"], \
        "conversation comments sit with the reviews by date, before the code threads"
    assert str(items[0]["row"]).splitlines()[1:] == ["alice", "Nice work, this reads well"], "a conversation comment shows its author and text"
    assert "alice commented" in Content.from_markup(items[0]["place"]).plain, "a conversation comment shows its author and text"
    assert "Nice work, this reads well" in Content.from_markup("\n".join(items[0]["comments"])).plain, \
        "a conversation comment shows its author and text"
    assert items[0]["url"] == NOTE["url"], "enter on a conversation comment opens that comment"
    assert "comments 4 · c to open" in Content.from_markup(entries.pr_entry(pr, {}, STATED).detail).plain, \
        "the detail counts conversation comments too"


def test_pr_detail_status_and_activity():
    commits = [{"committedDate": at} for at in ("2026-10-23T08:00:00Z", "2026-10-23T15:00:00Z", "2026-10-21T11:00:00Z")]
    pr = replace(PR_TWO, commits=commits, ci="failing")
    lines = Content.from_markup(entries.pr_entry(pr, {}, STATED).detail).plain.splitlines()
    assert "status   approved · red CI" in lines, "the detail says in one line what the pr is missing, as its row does"
    assert not any(line.startswith(("review ", "ci ", "merge ")) for line in lines), "the status line replaces review, ci and merge"
    assert f"last push {days_since('2026-10-23T15:00:00Z')}d ago" in next(line for line in lines if line.startswith("pr ")), \
        "the pr line says how long ago the last commit was pushed"
    activity = lines[lines.index("── activity ──") + 1:]
    assert [line for line in activity if "commit" in line] == ["Oct 23        2 commits", "Oct 21        1 commit"], \
        "activity groups the commits of a day in one line"
    asked = Content.from_markup(entries.pr_entry(replace(PR_ONE, reviews=[], ci="passing", mergeable="MERGEABLE"), {}, STATED, asked=True).detail).plain
    assert "status   your review" in asked, "a pr waiting on your review says so in its status line"
    assert "last push" not in Content.from_markup(entries.pr_entry(PR_TWO, {}, STATED).detail).plain, \
        "a pr without commits shows no last push"


def test_pr_detail_links_the_failed_checks():
    checks = [{"name": "rspec", "url": "https://ci/rspec"}, {"name": "ci/jenkins", "url": "https://jenkins/1"}]
    detail = entries.pr_entry(replace(PR_TWO, ci="failing", failed_checks=checks), {}, STATED).detail
    assert "failing  rspec · ci/jenkins" in Content.from_markup(detail).plain.splitlines(), "the detail names each failed check"
    assert "app.open_link('https://ci/rspec')" in detail, "a failed check opens its log"
    assert "failing " not in Content.from_markup(entries.pr_entry(PR_TWO, {}, STATED).detail).plain, "a pr with no failed check names none"


def test_activity_days():
    commits = [{"committedDate": at} for at in ("2026-10-23T21:30:00Z", "2026-10-23T22:30:00Z", "2025-10-23T08:00:00Z")]
    lines = Content.from_markup(entries.pr_entry(replace(PR_TWO, commits=commits), {}, STATED).detail).plain.splitlines()
    activity = [line for line in lines[lines.index("── activity ──") + 1:] if "commit" in line]
    assert activity == ["Oct 24        1 commit", "Oct 23        1 commit", "Oct 23 2025   1 commit"], \
        "activity groups commits by the local day, so a late UTC commit lands on the next day, and last year's day names its year"
    assert f"last push {(dt.date.today() - dt.date(2026, 10, 24)).days}d ago" in next(line for line in lines if line.startswith("pr ")), \
        "the last push counts days on the local calendar, as the activity does"


def test_change_detail_shows_the_timeline_of_its_group():
    ticket = {"at": "2026-10-25T09:00", "tone": "commented", "label": "In review", "item": "https://acme.atlassian.net/browse/ACME-1",
              "group": PR_ONE.url, "subject": {"kind": "ticket", "url": "https://acme.atlassian.net/browse/ACME-1", "ref": "ACME-1",
                                               "title": "Ticket one"}, "note": None, "aside": "was: In Progress", "told": False}
    pushed = {**board([])["changes"][0], "at": "2026-10-25T08:00", "tone": "waiting", "label": "New commits", "told": True}
    history = [{"at": "2026-10-25T06:30:00Z", "state": None, "author": None}, {"at": "2026-10-25T05:00:00Z", "state": "APPROVED", "author": "bob"}]
    found = entries.entries({**board([]), "changes": [ticket, pushed], "histories": {PR_ONE.url: history}}, STATED)["changes"]
    assert [entry.cells[1][0] for entry in found] == ["in review"], "the changes box shows one row per pr, with its latest change"
    lines = Content.from_markup(found[0].detail).plain.splitlines()
    assert lines[lines.index("── timeline ──") + 1:] == ["Oct 25 09:00  In Progress → In review ACME-1", "Oct 25        1 commit",
                                                         "Oct 25 06:00  approved bob"], \
        "the detail lists the pr's history and its ticket's moves newest first, without the commits and reviews told twice"


def test_change_timeline_shows_the_history_the_board_carries():
    history = [{"at": "2026-10-25T05:00:00Z", "state": "APPROVED", "author": "bob"}]
    detail = entries.entries({**board([PR_ONE]), "histories": {PR_ONE.url: history}}, STATED)["changes"][0].detail
    lines = Content.from_markup(detail).plain.splitlines()
    assert lines[lines.index("── timeline ──") + 1:] == ["Oct 25 06:00  approved bob", "Oct 24 02:04  New PR"], \
        "the timeline shows the pr history the board carries, without naming the pr it belongs to"


def test_change_timeline_shows_a_status_move_from_the_old_state():
    moved = {**board([])["changes"][0], "tone": "waiting", "label": "Awaiting review", "aside": "was: Draft"}
    detail = entries.entries({**board([]), "changes": [moved], "histories": {PR_ONE.url: []}}, STATED)["changes"][0].detail
    lines = Content.from_markup(detail).plain.splitlines()
    assert lines[lines.index("── timeline ──") + 1:] == ["Oct 24 02:04  Draft → Awaiting review"], \
        "a status change reads as its move from the old state to the new one"


def test_change_timeline_keeps_an_aside_that_is_no_move():
    reviewed = {**board([])["changes"][0], "label": "Commented", "aside": "new review"}
    detail = entries.entries({**board([]), "changes": [reviewed], "histories": {PR_ONE.url: []}}, STATED)["changes"][0].detail
    lines = Content.from_markup(detail).plain.splitlines()
    assert lines[lines.index("── timeline ──") + 1:] == ["Oct 24 02:04  Commented new review"], \
        "a change that is no status move keeps its aside after its label"


def test_a_change_row_names_who_opened_its_pr():
    opened = {**board([PR_ONE])["changes"][0], "subject": SUBJECT}
    moved = {**opened, "at": "2026-10-24T03:00", "label": "In review", "subject": {"kind": "ticket", "url": "u", "ref": "ACME-1", "title": "T"}}
    row = entries.entries({**board([PR_ONE]), "changes": [moved, opened]}, STATED)["changes"][0]
    assert row.cells[2] == ("alice", "dim"), "a change row names who opened its group's pr, even when a ticket move leads the group"
    alone = entries.entries({**board([]), "changes": [{**moved, "group": "u", "item": "u"}]}, STATED)["changes"][0]
    assert alone.cells[2] == ("", "dim"), "a ticket's own change row names nobody"


def test_change_detail_names_the_pr_beside_its_state():
    detail = entries.entries({**board([PR_ONE]), "histories": {PR_ONE.url: []}}, STATED)["changes"][0].detail
    lines = Content.from_markup(detail).plain.splitlines()
    head = lines[:lines.index("── timeline ──")]
    assert head[0] == "New PR - app#1" and len(head) == 4, "a pr change names its pr beside its state, and nowhere else above the timeline"
    assert not any(line.startswith("at ") for line in head), "the change detail leaves its time to the heading and the timeline"


def test_change_detail_of_a_ticket_names_it_once():
    subject = {"kind": "ticket", "url": "https://acme.atlassian.net/browse/ACME-1", "ref": "ACME-1", "title": "Ticket one"}
    moved = {**board([])["changes"][0], "label": "In review", "subject": subject, "item": subject["url"], "group": subject["url"]}
    lines = Content.from_markup(entries.entries({**board([]), "changes": [moved], "histories": {}}, STATED)["changes"][0].detail).plain.splitlines()
    assert lines[:4] == ["In review", "", "ACME-1 Ticket one", ""], "a ticket change already names its key in the title, so no line repeats it"


def test_change_timeline_shows_the_ten_newest():
    subject = {"kind": "ticket", "url": "https://acme.atlassian.net/browse/ACME-1", "ref": "ACME-1", "title": "Ticket one"}
    moves = [{"at": f"2026-10-25T{hour:02d}:00", "tone": "commented", "label": "In review", "item": subject["url"], "group": subject["url"],
              "subject": subject, "note": "joins the epics", "aside": None, "told": False} for hour in range(12, 0, -1)]
    detail = entries.entries({**board([]), "changes": moves, "histories": {}}, STATED)["changes"][0].detail
    lines = Content.from_markup(detail).plain.splitlines()
    timeline = lines[lines.index("── timeline ──") + 1:]
    assert len(timeline) == 10, "the timeline keeps the ten newest lines"
    assert timeline[0] == "Oct 25 12:00  In review ACME-1 joins the epics", "a change in the timeline reads its label, ref and note"


def test_factory_rows_flag_the_tickets_needing_you():
    now = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.timezone.utc)
    since = now - dt.timedelta(minutes=95)
    tone = {stage: entries.factory_entry(FactoryTicket("ACME-1", stage, "", since, None), now, STATED, None).cells[1][1].partition("-")[0]
            for stage in ("waiting-you", "review-blocked", "building", "ready")}
    assert tone["waiting-you"] in ("warn", "bad") and tone["review-blocked"] in ("warn", "bad"), \
        "a ticket waiting for you or blocked in review stands out in a warning or alarm color"
    assert tone["ready"] == "ok" and tone["building"] == "dim", "a ready ticket reads calm and a building one neutral"


def test_factory_row_shows_the_key_stage_age_and_session():
    now = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.timezone.utc)
    working = entries.factory_entry(FactoryTicket("ACME-1", "waiting-you", "which repo?", now - dt.timedelta(minutes=95), "working"), now, STATED, None)
    assert [value for value, _ in working.cells] == ["ACME-1", "waiting-you", "1h", "working", "which repo?"], \
        "a factory row shows the key, the stage, how long ago it changed, the herdr session and the detail"
    assert working.url == STATED.jira_browse + "ACME-1" and working.copy == "ACME-1", "a factory row opens its jira ticket and copies its key"
    detail = Content.from_markup(working.detail).plain
    assert all(text in detail for text in ["ACME-1", "waiting-you", "1h ago", "working", "which repo?"]), \
        "a factory row's details repeat its stage, age, session and detail"
    absent = entries.factory_entry(FactoryTicket("ACME-2", "building", "", None, None), now, STATED, None)
    assert [value for value, _ in absent.cells][2:4] == ["", "absent"], "a ticket with no herdr session reads absent, and an undated stage has no age"


FACTORY_NOW = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.timezone.utc)


def factory_detail(ticket, found_board):
    return Content.from_markup(entries.factory_entry(ticket, FACTORY_NOW, STATED, found_board).detail).plain


def test_factory_detail_tells_the_ticket_and_its_epic():
    detail = factory_detail(FactoryTicket("ACME-1", "ready", "", FACTORY_NOW, None), board([PR_ONE]))
    assert detail.startswith("Ticket one"), "a factory ticket on the board heads its details with its summary"
    assert "(In Progress)" in detail and "ACME-100 Epic one" in detail, "a factory ticket's details tell its jira status and epic"


def test_factory_detail_finds_an_epics_ticket_without_its_epic():
    found = {**board([PR_ONE]), "my_tickets": []}
    detail = factory_detail(FactoryTicket("ACME-2", "ready", "", FACTORY_NOW, None), found)
    assert detail.startswith("Ticket two") and "(Done)" in detail and "epic" not in detail, \
        "a factory ticket only an epic lists still tells its summary and status, without an epic line it has no details for"


def test_factory_detail_lists_the_prs_naming_the_ticket():
    pr = replace(PR_ONE, failed_checks=[{"name": "lint", "url": "https://ci.example/1"}])
    detail = factory_detail(FactoryTicket("ACME-1", "ready", "", FACTORY_NOW, None), board([pr, PR_TWO]))
    assert "app#1 Awaiting review · CI red" in detail and "failing  lint" in detail and "#2" not in detail, \
        "a factory ticket's details list the prs that name it, with their review, ci and failing checks, and no other pr"


def test_factory_detail_ends_with_what_the_agent_wrote():
    ticket = FactoryTicket("ACME-1", "ready", "", FACTORY_NOW, "idle", "w1:p1", ("⏺ PR ready for review", "  - CI green"))
    detail = factory_detail(ticket, board([PR_ONE]))
    assert detail.index("── agent ──") < detail.index("⏺ PR ready for review") < detail.index("  - CI green"), \
        "a factory ticket's details end with what its agent last wrote, in order"


def test_factory_detail_offers_g_only_with_a_session():
    with_pane = factory_detail(FactoryTicket("ACME-1", "ready", "", FACTORY_NOW, "idle", "w1:p1"), None)
    without = factory_detail(FactoryTicket("ACME-1", "ready", "", FACTORY_NOW, None), None)
    assert "g jumps to it" in with_pane and "g jumps to it" not in without, "the details offer g only for a ticket whose herdr session runs"


def test_factory_row_shows_the_summary_when_the_stage_has_no_detail():
    entry = entries.factory_entry(FactoryTicket("ACME-1", "ready", "", FACTORY_NOW, None), FACTORY_NOW, STATED, board([PR_ONE]))
    assert entry.cells[-1][0] == "Ticket one" and "Ticket one" in entry.search, \
        "a factory row without a stage detail shows the ticket's summary, and the filter finds it by it"


def test_factory_detail_without_a_board_keeps_the_stage():
    now = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.timezone.utc)
    entry = entries.factory_entry(FactoryTicket("ACME-9", "building", "", now, None), now, STATED, None)
    detail = Content.from_markup(entry.detail).plain
    assert detail.startswith("ACME-9") and "building" in detail and "agent" not in detail, \
        "a factory ticket the board does not know heads its details with its key, and one without a session shows no agent output"


def test_a_kanban_ticket_without_detail_or_assignee():
    cells = [value for value, _ in entries.kanban_entry(Ticket(key="OPS-7", summary="Ticket seven", status="Tareas por hacer"), [], STATED, True).cells]
    assert cells[1:3] == ["", ""] and cells[4] == "", \
        "a ticket of mine off the board, cached before its detail, shows no blocked mark, no assignee and no age"


def test_ticket_description_fits_the_space_it_has():
    ticket = Ticket(key="ACME-1", summary="Ticket one", status="En proceso", detail=replace(
        TICKET_DETAIL, description="\n".join(f"line {n}" for n in range(1, 31))))
    entry = entries.ticket_entry(ticket, [], STATED)
    whole = len(Content.from_markup(entry.detail).wrap(60))
    assert entries.fitted(entry.detail, entry.fold, 60, whole) == entry.detail, "a description that fits the box shows whole"
    fitted = Content.from_markup(entries.fitted(entry.detail, entry.fold, 60, whole - 5)).wrap(60)
    assert len(fitted) == whole - 5, "a description that does not fit fills the box to its last line"
    assert fitted[-1].plain == "… c to read it all", "a description that does not fit ends on the hint to read it all"


def test_ticket_description_one_row_short_trades_its_last_lines_for_the_hint():
    ticket = Ticket(key="ACME-1", summary="Ticket one", status="En proceso", detail=replace(
        TICKET_DETAIL, description="\n".join(f"line {n}" for n in range(1, 31))))
    entry = entries.ticket_entry(ticket, [], STATED)
    whole = len(Content.from_markup(entry.detail).wrap(60))
    fitted = entries.fitted(entry.detail, entry.fold, 60, whole - 1)
    assert "line 28\n" in fitted and "line 29" not in fitted, "a box one row short drops the last two lines for the hint"
    assert entries.fitted(entry.detail, entry.fold, 60, 3) == entries.folded(entry.detail, entry.fold, 0), \
        "a box shorter than the heading keeps no description line"


def test_ticket_description_fits_by_the_rows_its_lines_wrap_to():
    ticket = Ticket(key="ACME-1", summary="Ticket one", status="En proceso", detail=replace(
        TICKET_DETAIL, description="\n".join(f"line {n} " + "word " * 20 for n in range(1, 31))))
    entry = entries.ticket_entry(ticket, [], STATED)
    rows = Content.from_markup(entries.fitted(entry.detail, entry.fold, 60, 40)).wrap(60)
    assert len(rows) <= 40 and rows[-1].plain == "… c to read it all", "a description whose lines wrap is cut by the rows they take, not by its lines"


def test_ticket_description_in_a_narrow_box_shows_whole_when_it_fits():
    detail = "KEY-1\n\n── description\na\nb"
    assert entries.fitted(detail, 2, 17, 5) == detail, "a description that fits a box too narrow for the hint on one row shows whole"


def test_a_detail_without_description_is_never_cut():
    assert entries.fitted("KEY-1\n" * 10, 0, 60, 3) == "KEY-1\n" * 10, "a detail without a description shows whole, whatever the box"
