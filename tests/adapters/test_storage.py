import json
from pathlib import Path

from magi.adapters import storage


def test_storage(tmp_path):
    path = tmp_path / "nested" / "data.json"
    assert storage.read(path) is None, "a missing file reads as nothing"
    storage.write(path, {"board": {"ñ": 1}})
    assert storage.read(path) == {"board": {"ñ": 1}}, "a written file reads back, in a folder created on demand"
    assert sorted(p.name for p in path.parent.iterdir()) == ["data.json"], "a full write leaves no temp file"
    path.write_text('{"board": {}}')
    assert storage.read(path) is None, "a file from before versioning reads as nothing"
    for version in (storage.VERSION - 1, storage.VERSION + 1):
        path.write_text(f'{{"version": {version}, "board": {{}}}}')
        assert storage.read(path) is None, f"a file from another version reads as nothing: {version}"
    path.write_text('{"version": ')
    assert storage.read(path) is None, "a half-written file reads as nothing"
    for content in ("[]", "null", '"text"'):
        path.write_text(content)
        assert storage.read(path) is None, f"json that is not an object reads as nothing: {content}"
    path.write_bytes('{"name": "Mart'.encode()[:-1] + "í".encode()[:1])
    assert storage.read(path) is None, "a file cut inside a utf-8 character reads as nothing"


def test_storage_crash(tmp_path, monkeypatch):
    path = tmp_path / "data.json"
    storage.write(path, {"kept": True})

    def crash(target, text, **options):
        target.open("w").close()
        raise OSError("disk full")
    monkeypatch.setattr(Path, "write_text", crash)
    try:
        storage.write(path, {"kept": False})
    except OSError:
        pass
    monkeypatch.undo()
    assert storage.read(path) == {"kept": True}, "a write cut off midway keeps the previous file"


def stamped(path, version, data):
    path.write_text(json.dumps({"version": version, **data}))


def test_storage_upgrades(tmp_path):
    path = tmp_path / "state.json"
    upgrades = {storage.VERSION - 2: lambda data: {**data, "steps": data["steps"] + ["a"]},
                storage.VERSION - 1: lambda data: {**data, "steps": data["steps"] + ["b"]}}
    stamped(path, storage.VERSION - 2, {"steps": []})
    assert storage.read(path, upgrades) == {"steps": ["a", "b"]}, "an older file is brought up one version at a time"
    stamped(path, storage.VERSION - 3, {"steps": []})
    assert storage.read(path, upgrades) is None, "a file a missing upgrade cannot bring up reads as nothing"
    stamped(path, storage.VERSION + 1, {"steps": []})
    assert storage.read(path, upgrades) is None, "a file from a newer version reads as nothing"


def test_json_files_upgrade_only_the_files_named(tmp_path):
    files = storage.JsonFiles({"state": tmp_path / "state.json", "prs": tmp_path / "prs.json"},
                              {"state": {storage.VERSION - 1: lambda data: {**data, "upgraded": True}}})
    for name in ("state", "prs"):
        stamped(tmp_path / f"{name}.json", storage.VERSION - 1, {})
    assert files.read("state") == {"upgraded": True}, "a file named in the upgrades is brought up"
    assert files.read("prs") is None, "a file with no upgrade of its own is dropped"


def test_write_text(tmp_path):
    path = tmp_path / "nested" / "board.html"
    storage.write_text(path, "<p>ñ</p>")
    assert path.read_text() == "<p>ñ</p>", "plain text is written as given, in a folder created on demand"
    assert sorted(p.name for p in path.parent.iterdir()) == ["board.html"], "a full write leaves no temp file"
