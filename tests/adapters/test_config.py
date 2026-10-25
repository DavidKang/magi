import json

from builders import SETTINGS
from magi import config


def test_config_ignores_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({**SETTINGS, "theme": "picard", "added_later": 1}))
    assert config.load(path) == config.Settings(**SETTINGS, theme="picard"), "a config written by a newer version still loads"

