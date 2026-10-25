import pytest

from tarkon import rows
from tarkon.tui import theme


@pytest.fixture
def aliases(monkeypatch):
    monkeypatch.setitem(rows.TUI_REPO_ALIASES, "billing-reconciliation-service", "brs")


@pytest.fixture
def default_theme():
    yield
    theme.use_theme("default")
