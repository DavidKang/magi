"""Per-user settings, kept in ~/.config/tarkon/config.json."""

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

PATH = Path.home() / ".config" / "tarkon" / "config.json"


@dataclass
class Settings:
    team: list
    jira_project: str
    github_user: str
    github_org: str
    jira_url: str

    @property
    def jira_browse(self):
        return f"{self.jira_url.rstrip('/')}/browse/"


FIELDS = [field.name for field in fields(Settings)]
settings = None


def use(found):
    global settings
    settings = found


def load(path=PATH):
    return Settings(**json.loads(path.read_text())) if path.exists() else None


def save(found, path=PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(found), indent=1))
