"""Json files written atomically and stamped with a version: a half-written file, or one from another version no upgrade covers, reads as missing.

Bump VERSION whenever the shape of a saved file changes, so an older file is dropped instead of breaking the app; one worth keeping
gets an upgrade from the previous version instead (magi.application.upgrades.UPGRADES).
"""

import dataclasses
import json

VERSION = 7


def write(path, data):
    write_text(path, json.dumps({"version": VERSION, **data}, default=encode, ensure_ascii=False))


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written aside and renamed, so quitting mid-write never leaves a truncated file.
    staged = path.with_name(path.name + ".tmp")
    staged.write_text(text, encoding="utf-8")
    staged.replace(path)


def encode(value):
    return dataclasses.asdict(value) if dataclasses.is_dataclass(value) else str(value)


def read(path, upgrades=()):
    """upgrades maps an older version to what brings its data one version up, so a file it covers is kept instead of dropped."""
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):  # ValueError covers bad json and bytes cut inside a utf-8 character
        return None
    if not isinstance(data, dict):
        return None
    version = data.pop("version", None)
    while version != VERSION:
        if version not in upgrades:
            return None
        data, version = upgrades[version](data), version + 1
    return data


class JsonFiles:
    """The refresh's store: each name it reads or writes is one of these json files."""

    def __init__(self, paths, upgrades=None):
        self.paths, self.upgrades = paths, upgrades or {}

    def read(self, name):
        return read(self.paths[name], self.upgrades.get(name, ()))

    def write(self, name, data):
        write(self.paths[name], data)
