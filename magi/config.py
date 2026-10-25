"""Per-user settings, kept in ~/.config/magi/config.json."""

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

PATH = Path.home() / ".config" / "magi" / "config.json"


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


def load(path=PATH):
    if not path.exists():
        return None
    names = {field.name for field in fields(Settings)}
    return Settings(**{name: value for name, value in json.loads(path.read_text()).items() if name in names})


def save(found, path=PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(found), indent=1))
