import json

from builders import SETTINGS
from tarkon import config


def test_config_ignores_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({**SETTINGS, "theme": "voyager", "added_later": 1}))
    assert config.load(path) == config.Settings(**SETTINGS, theme="voyager"), "a config written by a newer version still loads"


def test_config_reads_the_old_lcars_theme_as_okuda(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({**SETTINGS, "theme": "lcars"}))
    assert config.load(path) == config.Settings(**SETTINGS, theme="okuda"), "the LCARS theme became Okuda's"
