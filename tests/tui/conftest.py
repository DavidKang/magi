import pytest

from tarkon import rows
from tarkon.tui import screens, theme


@pytest.fixture
def aliases(monkeypatch):
    monkeypatch.setitem(rows.TUI_REPO_ALIASES, "billing-reconciliation-service", "brs")


@pytest.fixture
def default_theme():
    yield
    theme.use_theme("default")


@pytest.fixture(autouse=True)
def graphics(monkeypatch):
    """Tests run without a TTY; draw the logo as a terminal with Sixel or Kitty graphics would."""
    monkeypatch.setattr(screens, "GRAPHICS", True)
