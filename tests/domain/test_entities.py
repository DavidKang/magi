from builders import pr_node
from magi.adapters import github, jira, process, storage
from magi.domain.entities import Epic, PullRequest, Ticket


def test_entities(tmp_path, monkeypatch):
    monkeypatch.setattr(process, "run_json", lambda cmd: {"data": {"pr0": pr_node(2, None)}})
    assert isinstance(github.fetch_prs([("capsulecorp/radar", 2)])[0], PullRequest), "a pr fetch builds pull requests"
    monkeypatch.setattr(process, "run_json", lambda cmd: [{"key": "KAME-9", "fields": {
        "summary": "S", "status": {"name": "Rollout"}, "assignee": None}}])
    assert isinstance(jira.fetch_children("KAME-9")[0], Ticket), "an epic's children are tickets"
    path = tmp_path / "entities.json"
    storage.write(path, {"epic": Epic("KAME-1", "S", "Rollout", "Chichi")})
    assert storage.read(path) == {"epic": {"key": "KAME-1", "summary": "S", "status": "Rollout", "owner": "Chichi"}}, \
        "storage writes an entity as its fields"
