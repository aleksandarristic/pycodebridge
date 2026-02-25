import json
import tarfile
import time

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
