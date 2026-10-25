"""Json files written atomically and stamped with a version: a half-written file, or one from another version, reads as missing.

Bump VERSION whenever the shape of the saved board or state changes, so an older file is dropped instead of breaking the app.
"""

import dataclasses
import json

VERSION = 3


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written aside and renamed, so quitting mid-write never leaves a truncated file.
    staged = path.with_name(path.name + ".tmp")
    staged.write_text(json.dumps({"version": VERSION, **data}, default=encode, ensure_ascii=False))
    staged.replace(path)


def encode(value):
    return dataclasses.asdict(value) if dataclasses.is_dataclass(value) else str(value)


def read(path):
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):  # ValueError covers bad json and bytes cut inside a utf-8 character
        return None
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return None
    del data["version"]
    return data
