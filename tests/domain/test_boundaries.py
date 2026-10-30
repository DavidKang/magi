import importlib

from builders import ROOT, imported, outside

DOMAIN = ROOT / "magi" / "domain"
STDLIB = {"dataclasses", "datetime", "math", "re"}
NAMES = {"entities": ["Epic", "FoundPr", "PullRequest", "Ticket", "TicketDetail", "ticket_from"],
         "status": ["ACTIVE_COLUMNS", "COLUMNS", "DISCARDED", "EPIC_STATUSES", "KANBAN_COLUMNS", "KANBAN_RANK", "STATUS_COLUMNS", "STATUS_LABELS", "STATUS_RANK", "UnmappedStatus",
                    "column_for", "kanban_order", "status_label", "ticket_order"],
         "labels": ["BLOCKED_LABEL", "blocked"],
         "keys": ["TICKET_KEY", "searched_keys", "ticket_keys_in", "title_keys_in", "title_parts"],
         "review": ["CI_LABELS", "STALE_PR_DAYS", "TURNS", "blockers", "looks_ready_but_blocked", "pr_events", "review_state", "standing", "turn", "turn_parts"],
         "changes": ["CHANGES_HOURS", "change_mark", "change_text", "changes_between", "group_author", "group_changes", "latest", "moved_from", "pr_subject",
                     "recent_changes", "snapshot", "snapshot_epics", "subject_text", "ticket_subject", "vanished_prs"],
         "histories": ["kept_histories", "pr_histories"],
         "mine": ["authored", "my_changes", "my_epics", "my_prs"],
         "snoozes": ["asleep", "awake", "change_marks"],
         "ages": ["AGE_UNITS", "ago", "days_since"],
         "factory": ["Agent", "FactoryTicket", "STAGES", "Stage", "factory_tickets", "session_of"]}


def test_domain_imports_only_itself_and_pure_stdlib():
    modules = sorted(DOMAIN.glob("*.py"))
    assert modules, "the domain lives in magi/domain"
    for path in modules:
        reached = outside(imported(path, "magi.domain"), STDLIB, ["magi.domain"])
        assert reached == [], f"{path.name} reaches outside the domain: {reached}"


def test_domain_holds_the_board_rules():
    for module, names in NAMES.items():
        found = importlib.import_module(f"magi.domain.{module}")
        assert [name for name in names if not hasattr(found, name)] == [], f"magi.domain.{module} holds its rules"


def test_a_package_is_matched_by_its_whole_name():
    assert outside(["magi.domain", "magi.domain.keys", "magi.domainx", "re", "json"], STDLIB, ["magi.domain"]) == ["magi.domainx", "json"], \
        "a sibling package that only shares the prefix is outside, like any stdlib module not allowed"
