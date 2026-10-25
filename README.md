<p align="center"><img src="assets/logo.png" alt="Tarkon logo" width="160"></p>

# Tarkon

Your team's board in one screen: the PRs that need you, the team's open PRs, what changed in the last 24 hours, the progress of every epic in Developing or Rollout, and your own open PRs and Jira tickets. It reads Jira through `acli` and GitHub through `gh`, and runs in the terminal or as a browser page.

## Quick path

1. Install the requirements: Python 3.12+, [pipx](https://pipx.pypa.io), and both CLIs, logged in.
   ```bash
   brew install pipx gh
   brew tap atlassian/homebrew-acli && brew install acli
   gh auth login
   acli jira auth login
   ```
2. Install Tarkon from a clone of this repo.
   ```bash
   pipx install --python python3.12 .
   ```
3. Run `tarkon`. The first run opens the settings panel; fill it in and save with `ctrl+s`.

## Commands

| Command | What it does |
|---------|--------------|
| `tarkon` | Opens the board in the terminal |
| `tarkon config` | Opens the settings panel |
| `tarkon html` | Writes the browser page and prints its path |

## Settings

| Field | Example |
|-------|---------|
| GitHub users of your team | `alice, bob, carol` |
| Jira project | `ACME` |
| Your GitHub user | `alice` |
| GitHub organization | `acme` |
| Jira site | `https://acme.atlassian.net` |

Epics are not configured: the board shows every epic of the project in Developing or Rollout, newest first.

The browser page has three designs, picked from the switch in its header and remembered by the browser: `Console`, `Terminal` and `LCARS`.

## Keys

| Key | Action |
|-----|--------|
| `1` / `2` | Switch to the `Overview` tab or the `Mine` tab |
| `3`-`6` | Jump to the `Overview` tab's boxes: attention, team PRs, changes, epics |
| `7`-`8` | Jump to the `Mine` tab's boxes: your open PRs, your Jira tickets not done, grouped by status |
| `j` / `k` | Move down / up |
| `enter` | Open the selected item in the browser |
| `c` | Open the selected PR's comments, reviews and code threads with their diff, or the selected ticket's description and comments (`j`/`k` move, `enter` opens it in the browser, `esc` closes) |
| `/` | Filter the current box (`escape` clears it) |
| `y` | Copy the selected link (the key, for an epic) |
| `r` | Refresh (once every 30 seconds at most; it also refreshes every 5 minutes) |
| `t` | Switch between the default theme and the LCARS one (Star Trek's computer screens); the choice is saved in your settings |
| `q` | Quit |

## Where it keeps its files

| Path | Content |
|------|---------|
| `~/.config/tarkon/config.json` | Your settings |
| `~/.local/state/tarkon/state.json` | Last snapshot, used to detect changes |
| `~/.local/state/tarkon/board.html` | The browser page |
| `~/.cache/tarkon/cache.json` | Last board, shown while the next refresh runs; a cache from another version is dropped |
| `~/.cache/tarkon/prs.json` | Comments, reviews and threads of the PRs on the board, reused until a PR changes |
| `~/.cache/tarkon/updated.json` | When each in-progress ticket last changed, refetched only for tickets Jira reports as changed |
| `~/.cache/tarkon/my-tickets.json` | Details of your own tickets, refetched only for tickets Jira reports as changed |
| `~/.cache/tarkon/last-refresh` | When the last refresh started, so reopening the app or pressing `r` waits 30 seconds |

## Limits

- macOS only: opening links and copying use `open` and `pbcopy`.
- Jira columns are mapped from Spanish status names (`En proceso`, `Finalizado`...).
- PR searches use GitHub's GraphQL API, about 13 per refresh at 1 point each, out of 5000 points an hour. A PR's comments, reviews and threads are fetched again only when the PR changed.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/python scripts/profile_refresh.py  # one real refresh, timed per call; leaves your files alone
```

`board.py` builds the board as data from the `jira.py` and `github.py` adapters; `tui/` and `html/` render it, and both show PR and ticket rows from `rows.py`.
