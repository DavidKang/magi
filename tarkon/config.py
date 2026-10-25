"""Per-user settings, kept in ~/.config/tarkon/config.json."""

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

PATH = Path.home() / ".config" / "tarkon" / "config.json"


@dataclass
class Settings:
    team: list
    jira_project: str
    github_user: str
    github_org: str
    jira_url: str
    theme: str = "default"

    @property
    def jira_browse(self):
        return f"{self.jira_url.rstrip('/')}/browse/"


settings = None


def use(found):
    global settings
    settings = found


# Themes no longer offered, read as the closest one still offered so an old config still starts.
DROPPED_THEMES = {"lcars": "okuda", "voyager": "okuda", "magi": "nerv"}


def load(path=PATH):
    if not path.exists():
        return None
    names = {field.name for field in fields(Settings)}
    found = Settings(**{name: value for name, value in json.loads(path.read_text()).items() if name in names})
    return replace(found, theme=DROPPED_THEMES[found.theme]) if found.theme in DROPPED_THEMES else found


def save(found, path=PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(found), indent=1))
