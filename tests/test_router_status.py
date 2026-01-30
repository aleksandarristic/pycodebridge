from codebridge.router_status import format_current_selection_line, format_session_line
from codebridge.state import SessionState


def _make_session(model: str = "", reasoning: str = "", thread_id: str = "thread-1", last_used: str = "now") -> SessionState:
    return SessionState(
        repo_name="repo",
        repo_path="/tmp/repo",
        thread_id=thread_id,
        model=model,
        reasoning_effort=reasoning,
        created_at="",
        last_used_at=last_used,
    )


def test_format_session_line_includes_active_suffix():
    sess = _make_session(model="gpt-5.2")
    line = format_session_line("default", sess, True, "gpt-5", "medium")
    assert " (active)" in line
    assert "model gpt-5.2" in line
    assert "reasoning medium" in line


def test_format_session_line_falls_back_to_defaults():
    sess = _make_session()
    line = format_session_line("default", sess, False, "gpt-5", "high")
    assert " (active)" not in line
    assert "model gpt-5" in line
    assert "reasoning high" in line


def test_format_current_selection_line_allows_empty_values():
    line = format_current_selection_line("default", "gpt-5", "")
    assert "model gpt-5" in line
    assert "reasoning" not in line


def test_format_current_selection_line_includes_reasoning():
    line = format_current_selection_line("foo", "gpt-5", "extra-high")
    assert line.endswith("reasoning extra-high")
