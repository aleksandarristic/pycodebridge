"""Focused tests for ClaudeBackend — arg building and stream-json parsing."""

import json

import pytest

from codebridge.agents.claude import ClaudeBackend


def _backend(**kwargs) -> ClaudeBackend:
    return ClaudeBackend(binary="claude", **kwargs)


# ---------------------------------------------------------------------------
# _base_args / arg building
# ---------------------------------------------------------------------------

class TestBaseArgs:
    def test_minimal(self):
        b = _backend()
        args = b._base_args("/repo", "", "")
        assert args[:4] == ["-p", "--output-format", "stream-json", "--verbose"]
        assert "--add-dir" in args
        assert "/repo" in args

    def test_model_from_call(self):
        b = _backend()
        args = b._base_args("/repo", "claude-haiku-4-5", "")
        assert "--model" in args
        assert args[args.index("--model") + 1] == "claude-haiku-4-5"

    def test_model_from_default(self):
        b = _backend(model="claude-sonnet-4-6")
        args = b._base_args("/repo", "", "")
        assert "--model" in args
        assert args[args.index("--model") + 1] == "claude-sonnet-4-6"

    def test_call_model_overrides_default(self):
        b = _backend(model="default-model")
        args = b._base_args("/repo", "override", "")
        assert args[args.index("--model") + 1] == "override"

    def test_effort_from_call(self):
        b = _backend()
        args = b._base_args("/repo", "", "high")
        assert "--effort" in args
        assert args[args.index("--effort") + 1] == "high"

    def test_no_model_no_effort_when_empty(self):
        b = _backend()
        args = b._base_args("/repo", "", "")
        assert "--model" not in args
        assert "--effort" not in args

    def test_bypass_permissions(self):
        b = _backend(permission_mode="bypassPermissions")
        args = b._base_args("/repo", "", "")
        assert "--dangerously-skip-permissions" in args
        assert "--permission-mode" not in args

    def test_custom_permission_mode(self):
        b = _backend(permission_mode="acceptEdits")
        args = b._base_args("/repo", "", "")
        assert "--permission-mode" in args
        assert args[args.index("--permission-mode") + 1] == "acceptEdits"

    def test_default_permission_mode_omitted(self):
        b = _backend(permission_mode="default")
        args = b._base_args("/repo", "", "")
        assert "--permission-mode" not in args
        assert "--dangerously-skip-permissions" not in args


class TestBuildArgs:
    def test_build_start_args_appends_prompt(self):
        b = _backend()
        args = b.build_start_args("/repo", "do the thing", "", "")
        assert args[-1] == "do the thing"

    def test_build_resume_args(self):
        b = _backend()
        args = b.build_resume_args("/repo", "sess-123", "continue", "", "")
        assert "--resume" in args
        idx = args.index("--resume")
        assert args[idx + 1] == "sess-123"
        assert args[-1] == "continue"

    def test_build_resume_last_args(self):
        b = _backend()
        args = b.build_resume_last_args("/repo", "continue", "", "")
        assert "--continue" in args
        assert args[-1] == "continue"


# ---------------------------------------------------------------------------
# parse() — stream-json events
# ---------------------------------------------------------------------------

class TestParse:
    def _line(self, obj: dict) -> str:
        return json.dumps(obj)

    def test_init_event(self):
        b = _backend()
        line = self._line({
            "type": "system",
            "subtype": "init",
            "session_id": "abc-123",
            "model": "claude-sonnet-4-6",
        })
        evt = b.parse(line)
        assert evt is not None
        assert evt.type == "init"
        assert evt.session_id == "abc-123"

    def test_system_non_init_ignored(self):
        b = _backend()
        line = self._line({"type": "system", "subtype": "something_else"})
        assert b.parse(line) is None

    def test_assistant_text(self):
        b = _backend()
        line = self._line({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Hello!"},
                    {"type": "thinking", "thinking": "I should greet."},
                ]
            },
        })
        evt = b.parse(line)
        assert evt is not None
        assert evt.type == "message"
        assert evt.texts == ["Hello!"]
        assert evt.thinking == ["I should greet."]

    def test_assistant_multiple_text_blocks(self):
        b = _backend()
        line = self._line({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Part 1"},
                    {"type": "text", "text": "Part 2"},
                ]
            },
        })
        evt = b.parse(line)
        assert evt is not None
        assert evt.texts == ["Part 1", "Part 2"]

    def test_assistant_no_text_blocks(self):
        b = _backend()
        line = self._line({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "toolu_x", "name": "Bash", "input": {"command": "ls"}},
                ]
            },
        })
        evt = b.parse(line)
        assert evt is not None
        assert evt.type == "message"
        assert evt.texts == []
        assert evt.tool_calls == [{"name": "Bash", "input": {"command": "ls"}}]

    def test_assistant_tool_use_extracted(self):
        b = _backend()
        line = self._line({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/foo.py"}},
                    {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "git status"}},
                    {"type": "text", "text": "Done"},
                ]
            },
        })
        evt = b.parse(line)
        assert evt is not None
        assert evt.texts == ["Done"]
        assert len(evt.tool_calls) == 2
        assert evt.tool_calls[0] == {"name": "Read", "input": {"file_path": "/foo.py"}}
        assert evt.tool_calls[1] == {"name": "Bash", "input": {"command": "git status"}}
        assert evt.thinking == []

    def test_assistant_thinking_extracted(self):
        b = _backend()
        line = self._line({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "I need to check the file."},
                    {"type": "thinking", "thinking": "Then edit it."},
                ]
            },
        })
        evt = b.parse(line)
        assert evt is not None
        assert evt.thinking == ["I need to check the file.", "Then edit it."]
        assert evt.texts == []
        assert evt.tool_calls == []

    def test_assistant_empty_thinking_skipped(self):
        b = _backend()
        line = self._line({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": ""},
                    {"type": "text", "text": "Hi"},
                ]
            },
        })
        evt = b.parse(line)
        assert evt is not None
        assert evt.thinking == []
        assert evt.texts == ["Hi"]

    def test_result_success(self):
        b = _backend()
        line = self._line({
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "Done",
            "session_id": "sess-456",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })
        evt = b.parse(line)
        assert evt is not None
        assert evt.type == "result"
        assert evt.session_id == "sess-456"
        assert evt.usage == {"input_tokens": 10, "output_tokens": 5}
        assert evt.error is None

    def test_result_error_via_is_error(self):
        b = _backend()
        line = self._line({
            "type": "result",
            "subtype": "error",
            "is_error": True,
            "result": "Something went wrong",
            "session_id": "sess-789",
        })
        evt = b.parse(line)
        assert evt is not None
        assert evt.type == "result"
        assert evt.error is not None
        assert evt.error["message"] == "Something went wrong"
        assert evt.error["subtype"] == "error"

    def test_result_error_via_subtype(self):
        b = _backend()
        line = self._line({
            "type": "result",
            "subtype": "error",
            "is_error": False,
            "result": "Oops",
            "session_id": "s",
        })
        evt = b.parse(line)
        assert evt is not None
        assert evt.error is not None

    def test_rate_limit_event_ignored(self):
        b = _backend()
        line = self._line({"type": "rate_limit_event", "rate_limit_info": {}})
        assert b.parse(line) is None

    def test_user_event_ignored(self):
        b = _backend()
        line = self._line({"type": "user", "message": {"role": "user", "content": []}})
        assert b.parse(line) is None

    def test_invalid_json_ignored(self):
        b = _backend()
        assert b.parse("not json at all") is None

    def test_raw_preserved(self):
        b = _backend()
        line = self._line({"type": "system", "subtype": "init", "session_id": "x"})
        evt = b.parse(line)
        assert evt is not None
        assert evt.raw == line
