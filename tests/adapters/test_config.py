import json

import pytest

from builders import SETTINGS
from tarkon import config


def test_config_ignores_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({**SETTINGS, "theme": "picard", "added_later": 1}))
    assert config.load(path) == config.Settings(**SETTINGS, theme="picard"), "a config written by a newer version still loads"


def test_config_reads_the_old_lcars_theme_as_okuda(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({**SETTINGS, "theme": "lcars"}))
    assert config.load(path) == config.Settings(**SETTINGS, theme="okuda"), "the LCARS theme became Okuda's"


def test_config_reads_the_dropped_voyager_theme_as_okuda(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({**SETTINGS, "theme": "voyager"}))
    assert config.load(path) == config.Settings(**SETTINGS, theme="okuda"), "the Voyager theme was dropped for Okuda's"


@pytest.mark.parametrize("saved", ["magi", "nerv"])
def test_config_reads_a_saved_nerv_theme_as_nerv_magi(tmp_path, saved):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({**SETTINGS, "theme": saved}))
    assert config.load(path) == config.Settings(**SETTINGS, theme="nerv"), "a saved MAGI or NERV theme loads NERV Magi"
