import json
import tarfile
import time

from codebridge.observability.audit import Redactor
from codebridge.observability.session_jsonl import SessionJsonlLogger


def test_session_jsonl_append_writes_single_stream_per_session(tmp_path):
    logger = SessionJsonlLogger(str(tmp_path))
    logger.append("chan", "default", "run.start", {"repo": "demo"}, repo_name="repo")
    logger.append("chan", "default", "codex.exit", {"code": 0}, repo_name="repo")

    path = tmp_path / "session_jsonl" / "active" / "chan" / "repo-repo__session-default.jsonl"
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["event"] == "run.start"
    assert first["repo_name"] == "repo"
    assert second["event"] == "codex.exit"


def test_session_jsonl_redacts_payloads_before_writing(tmp_path):
    logger = SessionJsonlLogger(str(tmp_path), redactor=Redactor())
    logger.append(
        "chan",
        "default",
        "run.start",
        {
            "args": [
                "exec",
                "--totp",
                "123456",
                "token=abc123",
                "sk-abcdefghijklmnopqrstuv",
            ],
            "stderr": "totp=654321 password = p@ss",
        },
        repo_name="repo",
    )

    path = tmp_path / "session_jsonl" / "active" / "chan" / "repo-repo__session-default.jsonl"
    raw = path.read_text(encoding="utf-8")
    assert "123456" not in raw
    assert "654321" not in raw
    assert "token=abc123" not in raw
    assert "sk-abcdefghijklmnopqrstuv" not in raw
    assert "password = p@ss" not in raw
    assert "<redacted>" in raw


def test_session_jsonl_cleanup_archives_old_active_files(tmp_path):
    logger = SessionJsonlLogger(str(tmp_path), active_retention_days=30)
    active = tmp_path / "session_jsonl" / "active" / "chan" / "repo-repo__session-default.jsonl"
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text('{"event":"old"}\n', encoding="utf-8")

    old = time.time() - (31 * 24 * 60 * 60)
    import os

    os.utime(active, (old, old))
    logger.cleanup()

    assert not active.exists()
    archive_dir = tmp_path / "session_jsonl" / "archive" / "chan"
    archives = list(archive_dir.glob("repo-repo__session-default-*.tgz"))
    assert archives
    with tarfile.open(archives[0], "r:gz") as tar:
        members = tar.getnames()
    assert "repo-repo__session-default.jsonl" in members


def test_session_jsonl_buffers_hot_events_until_forced_flush(tmp_path):
    logger = SessionJsonlLogger(str(tmp_path), flush_interval_seconds=3600, max_buffered_events=100)
    path = tmp_path / "session_jsonl" / "active" / "chan" / "repo-repo__session-default.jsonl"

    logger.append("chan", "default", "codex.jsonl", {"line": "a"}, repo_name="repo")
    logger.append("chan", "default", "discord.output", {"chunk": "b"}, repo_name="repo")
    assert not path.exists()

    logger.append("chan", "default", "run.complete", {"code": 0}, repo_name="repo")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["codex.jsonl", "discord.output", "run.complete"]


def test_session_jsonl_flushes_when_buffer_threshold_is_hit(tmp_path):
    logger = SessionJsonlLogger(str(tmp_path), flush_interval_seconds=3600, max_buffered_events=2)
    path = tmp_path / "session_jsonl" / "active" / "chan" / "repo-repo__session-default.jsonl"

    logger.append("chan", "default", "codex.jsonl", {"line": "a"}, repo_name="repo")
    assert not path.exists()
    logger.append("chan", "default", "codex.jsonl", {"line": "b"}, repo_name="repo")

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert [json.loads(line)["data"]["line"] for line in lines] == ["a", "b"]


def test_session_jsonl_session_paths_flushes_pending_entries(tmp_path):
    logger = SessionJsonlLogger(str(tmp_path), flush_interval_seconds=3600, max_buffered_events=100)
    logger.append("chan", "default", "codex.jsonl", {"line": "a"}, repo_name="repo")

    paths = logger.session_paths("chan", "default", repo_name="repo")
    active = tmp_path / "session_jsonl" / "active" / "chan" / "repo-repo__session-default.jsonl"
    assert active in paths
    assert active.read_text(encoding="utf-8").strip()


def test_session_jsonl_retries_buffered_lines_after_flush_failure(tmp_path, monkeypatch):
    logger = SessionJsonlLogger(str(tmp_path), flush_interval_seconds=3600, max_buffered_events=2)
    path = tmp_path / "session_jsonl" / "active" / "chan" / "repo-repo__session-default.jsonl"
    attempts = 0
    original = logger._append_lines

    def fail_once(target, lines):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("disk busy")
        return original(target, lines)

    monkeypatch.setattr(logger, "_append_lines", fail_once)
    logger.append("chan", "default", "codex.jsonl", {"line": "a"}, repo_name="repo")
    try:
        logger.append("chan", "default", "codex.jsonl", {"line": "b"}, repo_name="repo")
    except OSError:
        pass

    assert not path.exists()
    logger.append("chan", "default", "run.complete", {"code": 0}, repo_name="repo")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["codex.jsonl", "codex.jsonl", "run.complete"]
