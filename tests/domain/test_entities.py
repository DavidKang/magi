from builders import pr_node
from magi.adapters import github, jira, process, storage
from magi.domain.entities import Epic, PullRequest, Ticket


def test_entities(tmp_path, monkeypatch):
    monkeypatch.setattr(process, "run_json", lambda cmd: {"data": {"pr0": pr_node(2, None)}})
    assert isinstance(github.fetch_prs([("acme/app", 2)])[0], PullRequest), "a pr fetch builds pull requests"
    monkeypatch.setattr(process, "run_json", lambda cmd: [{"key": "ACME-9", "fields": {
        "summary": "S", "status": {"name": "Rollout"}, "assignee": None}}])
    assert isinstance(jira.fetch_children("ACME-9")[0], Ticket), "an epic's children are tickets"
    path = tmp_path / "entities.json"
    storage.write(path, {"epic": Epic("ACME-1", "S", "Rollout", "Ana")})
    assert storage.read(path) == {"epic": {"key": "ACME-1", "summary": "S", "status": "Rollout", "owner": "Ana"}}, \
        "storage writes an entity as its fields"
