
from codebridge.observability.audit import Logger


def test_audit_start_and_summaries(tmp_path):
    logger = Logger(str(tmp_path))
    entry = logger.start("chan", "default", "thread", {"ok": True, "repo_name": "repo"})
    entry.append_codex_line("{\"type\":\"event\"}")
    entry.append_discord_out("hello")
    entry.append_stderr("err")
    entry.close()

    summaries = logger.summaries("chan", "default", 5)
    assert summaries
    assert summaries[0].channel_id == "chan"
    assert summaries[0].session == "default"
    assert summaries[0].repo_name == "repo"
    assert summaries[0].started_at
    assert summaries[0].ended_at


def test_audit_uses_prefixed_session_and_thread_paths(tmp_path):
    logger = Logger(str(tmp_path))
    entry = logger.start("chan", "default", "thread-1", {"repo_name": "repo"})
    entry.close()
    assert "repo-repo__session-default" in entry.codex_path
    assert "thread-thread-1" in entry.codex_path
