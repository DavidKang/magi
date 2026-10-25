from builders import PR_TWO, STATED, light_node, pr_node, ticket_view
from magi.adapters import github, jira, process, storage
from magi.domain.entities import Epic, FoundPr, PullRequest, Ticket, TicketDetail


def test_entities(tmp_path, monkeypatch):
    monkeypatch.setattr(process, "run_json", lambda cmd: {"data": {"search": {"nodes": [light_node(PR_TWO)]}}})
    assert isinstance(github.search_prs("is:pr")[0], FoundPr), "a pr search builds found prs"
    monkeypatch.setattr(process, "run_json", lambda cmd: {"data": {"pr0": pr_node(2, None)}})
    assert isinstance(github.fetch_prs([("acme/app", 2)])[0], PullRequest), "a pr fetch builds pull requests"
    monkeypatch.setattr(process, "run_json", lambda cmd: [{"key": "ACME-9", "fields": {
        "summary": "S", "status": {"name": "Rollout"}, "assignee": None}}])
    assert isinstance(jira.fetch_epics(STATED)[0], Epic), "epics are built from jira"
    assert isinstance(jira.fetch_children("ACME-9")[0], Ticket), "an epic's children are tickets"
    monkeypatch.setattr(process, "run_json", lambda cmd: [{"key": "ACME-1", "fields": {"summary": "S", "status": {"name": "En proceso"}}}]
                        if cmd[3] == "search" else ticket_view(cmd[4]))
    mine = jira.fetch_my_tickets(lambda keys: {key: jira.fetch_ticket_detail(key) for key in keys})
    assert isinstance(mine[0], Ticket), "my tickets are tickets carrying their detail"
    assert isinstance(mine[0].detail, TicketDetail), "my tickets are tickets carrying their detail"
    path = tmp_path / "entities.json"
    storage.write(path, {"epic": Epic("ACME-1", "S", "Rollout", "Ana")})
    assert storage.read(path) == {"epic": {"key": "ACME-1", "summary": "S", "status": "Rollout", "owner": "Ana"}}, \
        "storage writes an entity as its fields"
    path.write_text('{"version": 2, "board": {}}')
    assert storage.read(path) is None, "files written before entities read as nothing"
