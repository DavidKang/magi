import os
import time

import pytest



@pytest.fixture(autouse=True, scope="session")
def madrid():
    os.environ["TZ"] = "Europe/Madrid"
    time.tzset()


@pytest.fixture
def cache(tmp_path):
    return tmp_path / "cache.json"
