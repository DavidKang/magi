import datetime as dt
import json
from pathlib import Path

import pytest

from magi.adapters import factory, paths
from magi.domain.factory import Agent, Stage

UTC = dt.timezone.utc

HERDR_LIST = {"id": "cli:agent:list", "result": {"agents": [
    {"agent": "claude", "agent_status": "working", "cwd": "/Users/me/projects/storefront-worktrees/ACME-12", "pane_id": "w9:p1"},
    {"agent": "claude", "agent_status": "done", "cwd": "/Users/me/projects/ledger-worktrees/ACME-7-fix-the-rounding/", "pane_id": "w9:p2"}]}}
RECORD = {"key": "ACME-1", "stage": "building", "detail": "", "updated_at": "2026-10-29T09:00:00+00:00"}
STAGE = Stage("ACME-1", "building", "", dt.datetime(2026, 10, 29, 9, 0, tzinfo=UTC))


@pytest.fixture
def stage_dir(tmp_path, monkeypatch):
    found = tmp_path / "factory"
    found.mkdir()
    monkeypatch.setattr(paths, "FACTORY_DIR", found)
    return found


def herdr(tmp_path, monkeypatch, script):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if script is not None:
        (bin_dir / "herdr").write_text(f"#!/bin/sh\n{script}\n")
        (bin_dir / "herdr").chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))


def write_stages(stage_dir, *records):
    for n, record in enumerate(records):
        (stage_dir / f"{n}.json").write_text(json.dumps(record))


def test_stages_are_the_stage_files_of_the_factory_folder(stage_dir):
    (stage_dir / "ACME-1.json").write_text(json.dumps(RECORD))
    (stage_dir / "ACME-2.json.tmp").write_text(json.dumps({**RECORD, "key": "ACME-2"}))
    (stage_dir / "ACME-3.launch.log").write_text("launched")
    assert factory.stages() == [STAGE], "the factory's stages are its <KEY>.json files, without half-written .tmp files or launch logs"


def test_a_stage_reads_its_detail_and_when_it_changed(stage_dir):
    write_stages(stage_dir, {**RECORD, "detail": "which repo?", "updated_at": "2026-10-29T08:30:00Z"})
    [stage] = factory.stages()
    assert (stage.detail, stage.since) == ("which repo?", dt.datetime(2026, 10, 29, 8, 30, tzinfo=UTC)), \
        "a stage reads its detail and when it changed"


def test_a_stage_with_an_unreadable_time_has_no_age(stage_dir):
    write_stages(stage_dir, {**RECORD, "updated_at": "yesterday"}, {k: v for k, v in RECORD.items() if k != "updated_at"})
    assert [stage.since for stage in factory.stages()] == [None, None], "a stage with an unreadable or missing time still lists, without an age"


def test_a_time_without_an_offset_reads_as_utc(stage_dir):
    write_stages(stage_dir, {**RECORD, "updated_at": "2026-10-29T09:00:00"})
    assert factory.stages() == [STAGE], "a stage time without an offset is UTC, so its age never breaks the board"


@pytest.mark.parametrize("detail", [None, 3, ["x"]], ids=["null", "number", "list"])
def test_a_detail_that_is_not_text_reads_empty(stage_dir, detail):
    write_stages(stage_dir, {**RECORD, "detail": detail})
    assert factory.stages() == [STAGE], "a detail that is not text reads empty instead of breaking the board's rows"


def test_records_that_are_not_a_stage_are_left_out(stage_dir):
    write_stages(stage_dir, RECORD, {"key": "ACME-2"}, {"stage": "ready"}, {"key": 4, "stage": "ready"}, {"key": "ACME-5", "stage": 5},
                 {**RECORD, "key": "not a key"}, {**RECORD, "key": "A-1\"']x[@click=app.quit]"})
    assert factory.stages() == [STAGE], "a record without a Jira key or a stage written as text is not a stage"


def test_unreadable_stage_files_are_skipped(stage_dir):
    (stage_dir / "ACME-1.json").write_text('{"key": "ACME-1", "sta')
    (stage_dir / "ACME-2.json").write_text('["ACME-2"]')
    (stage_dir / "ACME-3.json").write_bytes(b"\xff\xfe")
    assert factory.stages() == [], "a cut, foreign or undecodable file is skipped instead of failing the factory box"


def test_a_stage_file_you_cannot_read_is_skipped(stage_dir, monkeypatch):
    (stage_dir / "ACME-1.json").write_text(json.dumps(RECORD))
    (stage_dir / "ACME-2.json").write_text(json.dumps({**RECORD, "key": "ACME-2"}))
    read_text = Path.read_text

    def denied(path, *args, **kwargs):
        if path.name == "ACME-2.json":
            raise PermissionError(13, "Permission denied", str(path))
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    assert factory.stages() == [STAGE], "a stage file without read permission is skipped, the others still list"


def test_no_factory_folder_means_no_stages(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "FACTORY_DIR", tmp_path / "missing")
    assert factory.stages() == [], "before the factory ever ran there are no stages"


def test_agents_are_herdrs_agent_list(tmp_path, monkeypatch):
    herdr(tmp_path, monkeypatch, f"[ \"$*\" = 'agent list' ] && echo '{json.dumps(HERDR_LIST)}'")
    assert factory.agents() == [Agent("ACME-12", "working"), Agent("ACME-7-fix-the-rounding", "done")], \
        "the agents are what herdr agent list reports, each by the folder it works in and its status"


@pytest.mark.parametrize("script", [None, "exit 1", "echo not json", "echo '{\"error\": \"no server\"}'"],
                         ids=["missing", "failing", "garbled", "no result"])
def test_herdr_that_cannot_answer_means_no_agents(tmp_path, monkeypatch, script):
    herdr(tmp_path, monkeypatch, script)
    assert factory.agents() == [], "herdr missing or failing reads as no sessions: magi still shows the factory"


def test_agents_herdr_cannot_place_are_left_out(tmp_path, monkeypatch):
    listed = {"result": {"agents": ["claude", {"agent_status": "idle"}, {"cwd": None, "agent_status": "idle"},
                                    {"cwd": "/Users/me/projects/storefront-worktrees/ACME-12", "agent_status": 3}]}}
    herdr(tmp_path, monkeypatch, f"echo '{json.dumps(listed)}'")
    assert factory.agents() == [Agent("ACME-12", None)], \
        "an agent without a working folder is left out and a status that is not text reads as none, instead of freezing the factory"


def test_herdr_that_hangs_means_no_agents(tmp_path, monkeypatch):
    herdr(tmp_path, monkeypatch, "exec /bin/sleep 5")
    monkeypatch.setattr(factory, "HERDR_TIMEOUT", 0.2)
    assert factory.agents() == [], "a herdr that hangs past its timeout reads as no sessions instead of holding the factory box"
