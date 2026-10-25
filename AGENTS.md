# AGENTS.md

Tarkon is a terminal board of a team's Jira epics and GitHub PRs. The README covers usage, configuration, themes and data locations; this file covers what you need to change the code.

## Stack

- Python 3.12+, packaged with setuptools (`pyproject.toml`), entry point `tarkon = "tarkon.cli:main"`.
- [Textual](https://textual.textualize.io) for the TUI, `textual-image` and Pillow for the logo. No other runtime dependencies.
- GitHub through the `gh` CLI (`gh api graphql`), Jira through the Atlassian `acli` CLI. No HTTP clients, no tokens in the code.
- macOS only: links open with `open`, copies go through `pbcopy`.
- pytest for tests (extra `dev`).

## Architecture

Hexagonal, in four layers under `tarkon/`:

| Layer | Path | Holds |
|-------|------|-------|
| Domain | `domain/` | The board's rules: entities, status columns, review state, attention, changes, ages. Pure functions and dataclasses. |
| Application | `application/` | One refresh (`refresh.py`), which fetches through the protocols in `ports.py` (`Tickets`, `PullRequests`, `Store`, `Clock`) and returns the board as plain data. |
| Adapters | `adapters/` | The real ports: `github.py`, `jira.py`, `storage.py` (JSON files), `paths.py`, `clock.py`, `process.py` (subprocesses, parallel calls, tool checks). |
| UI | `tui/` | The Textual app (`app.py`, `app.tcss`), rows and detail text (`entries.py`), popups and the settings panel (`screens.py`), themes (`theme.py`). |

`cli.py` is the composition root: it wires the adapters into `Refresh` and hands `refresh().collect` to the TUI. `rows.py` builds PR and ticket rows as plain data; `config.py` reads and writes the settings.

Two rules are enforced by tests:

- `tests/domain/test_boundaries.py`: the domain imports only itself and `dataclasses`, `datetime`, `math`, `re`. It also pins which names each domain module exports.
- `tests/application/test_layering.py`: the application imports only itself, the domain and `concurrent`, `dataclasses`, `math`, `typing`. Anything else from the outside goes through a port.

A new external call is a new method on a port, a real implementation in `adapters/` and a fake in the tests.

## Themes

`theme.py` holds the palettes (`THEMES`) and which frame each theme draws (`FRAMES`: `lcars` or `nerv`; `default` has none). Per-frame text lives in `tui/app.py`: box names in `LCARS_NAMES` and `NERV_NAMES`, alert labels in `THEME_CONDITIONS`, title and tab caps in `TITLE_CAPS` and `TAB_CAPS`. A theme-specific change keeps the default theme unchanged, and the README tables under "Themes" follow it.

## Commands

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q                # whole suite, about a minute
.venv/bin/python -m pytest tests/tui -q      # TUI only
.venv/bin/python scripts/profile_refresh.py  # one real refresh, timed per call; needs gh and acli logged in
.venv/bin/python scripts/screenshots.py      # README screenshots; needs Ghostty, a Nerd Font and Screen Recording permission
```

Run pytest as `.venv/bin/python -m pytest`: the venv's `pytest` script may point at an older checkout path.

## Tests

- `tests/` mirrors `tarkon/`: `domain/`, `application/`, `adapters/`, `tui/`.
- `tests/builders.py` holds the fixtures (`board`, `make_pr`, `make_epic`, `settings_file`, ...) and the import helpers the layering tests use.
- TUI tests drive the real app with Textual's `run_test` pilot and a fake `load`; they never call `gh` or `acli`.
- The suite runs in `Europe/Madrid` (`tests/conftest.py`), and `tests/tui/conftest.py` pretends the terminal draws images.
- Every assert carries a message that states the rule it checks; write new ones the same way.
- Behavior changes start with a failing test.

## Conventions

- Match the surrounding code: short functions, module-level constants for tables, few comments, and only ones that say why.
- Commit subjects are lowercase, verb-first, no prefix and no ticket (`list team prs as LCARS crew reports, oldest first`).
- When a command, key, theme or file location changes, update the README in the same commit.
- `odd/` is git-ignored working notes.

## Release

Bump `version` in `pyproject.toml` and push a `v*` tag. `.github/workflows/homebrew.yml` then points the formula in `DavidKang/homebrew-tarkon` at the tag.
