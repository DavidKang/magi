import os
import time

import pytest

from builders import make_settings
from tarkon import config


@pytest.fixture(autouse=True, scope="session")
def madrid():
    os.environ["TZ"] = "Europe/Madrid"
    time.tzset()


@pytest.fixture
def settings():
    config.use(make_settings())
    yield
    config.use(None)


@pytest.fixture
def cache(tmp_path):
    return tmp_path / "cache.json"
