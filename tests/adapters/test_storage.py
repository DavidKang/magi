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
