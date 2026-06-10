"""Focused tests for GeminiBackend — arg building and stream-json parsing."""

import json

import pytest

from codebridge.agents.gemini import GeminiBackend


def _backend(**kwargs) -> GeminiBackend:
    return GeminiBackend(binary="gemini", **kwargs)


# ---------------------------------------------------------------------------
# _base_args / arg building
# ---------------------------------------------------------------------------

class TestBaseArgs:
    def test_minimal(self):
        b = _backend()
        args = b._base_args("")
        assert "-o" in args
        assert args[args.index("-o") + 1] == "stream-json"
        assert "--skip-trust" in args

    def test_model_from_call(self):
        b = _backend()
        args = b._base_args("gemini-2.5-flash")
        assert "-m" in args
        assert args[args.index("-m") + 1] == "gemini-2.5-flash"

    def test_model_from_default(self):
        b = _backend(model="gemini-2.5-pro")
        args = b._base_args("")
        assert "-m" in args
        assert args[args.index("-m") + 1] == "gemini-2.5-pro"

    def test_call_model_overrides_default(self):
        b = _backend(model="default-model")
        args = b._base_args("override")
        assert args[args.index("-m") + 1] == "override"

    def test_no_model_when_empty(self):
        b = _backend()
        args = b._base_args("")
        assert "-m" not in args

    def test_yolo_approval_mode(self):
        b = _backend(approval_mode="yolo")
        args = b._base_args("")
        assert "--approval-mode" in args
        assert args[args.index("--approval-mode") + 1] == "yolo"

    def test_auto_edit_approval_mode(self):
        b = _backend(approval_mode="auto_edit")
        args = b._base_args("")
        assert "--approval-mode" in args
        assert args[args.index("--approval-mode") + 1] == "auto_edit"

    def test_default_approval_mode_omitted(self):
        b = _backend(approval_mode="default")
        args = b._base_args("")
        assert "--approval-mode" not in args


class TestBuildArgs:
    def test_build_start_appends_prompt_via_flag(self):
        b = _backend()
        args = b.build_start_args("/repo", "do the thing", "", "")
        assert "-p" in args
        assert args[args.index("-p") + 1] == "do the thing"

    def test_build_resume_by_session_id(self):
        b = _backend()
        args = b.build_resume_args("/repo", "sess-abc", "continue", "", "")
        assert "--resume" in args
        idx = args.index("--resume")
        assert args[idx + 1] == "sess-abc"
        assert "-p" in args
        assert args[args.index("-p") + 1] == "continue"

    def test_build_resume_last(self):
        b = _backend()
        args = b.build_resume_last_args("/repo", "keep going", "", "")
        assert "--resume" in args
        assert args[args.index("--resume") + 1] == "latest"
        assert "-p" in args
        assert args[args.index("-p") + 1] == "keep going"

    def test_reasoning_effort_ignored(self):
        b = _backend()
        args = b.build_start_args("/repo", "hello", "", "high")
        assert "--effort" not in args
        assert "high" not in args


# ---------------------------------------------------------------------------
# parse() — stream-json events
# ---------------------------------------------------------------------------

class TestParse:
    def _line(self, obj: dict) -> str:
        return json.dumps(obj)

    def test_init_event(self):
        b = _backend()
        line = self._line({
            "type": "init",
            "session_id": "29ac53c5-4292-45fb-b133-b9f6ef6d8c6f",
            "model": "gemini-2.5-flash",
            "timestamp": "2026-06-09T09:03:40.391Z",
        })
        evt = b.parse(line)
        assert evt is not None
        assert evt.type == "init"
        assert evt.session_id == "29ac53c5-4292-45fb-b133-b9f6ef6d8c6f"

    def test_message_user_ignored(self):
        b = _backend()
        line = self._line({"type": "message", "role": "user", "content": "hello"})
        assert b.parse(line) is None

    def test_message_assistant(self):
        b = _backend()
        line = self._line({
            "type": "message",
            "role": "assistant",
            "content": "Hello there!",
            "delta": True,
        })
        evt = b.parse(line)
        assert evt is not None
        assert evt.type == "message"
        assert evt.texts == ["Hello there!"]

    def test_message_assistant_empty_content(self):
        b = _backend()
        line = self._line({"type": "message", "role": "assistant", "content": ""})
        evt = b.parse(line)
        assert evt is not None
        assert evt.texts == []

    def test_tool_use_ignored(self):
        b = _backend()
        line = self._line({
            "type": "tool_use",
            "tool_name": "run_shell_command",
            "tool_id": "abc",
            "parameters": {"command": "ls"},
        })
        assert b.parse(line) is None

    def test_tool_result_ignored(self):
        b = _backend()
        line = self._line({
            "type": "tool_result",
            "tool_id": "abc",
            "status": "success",
            "output": "file.txt",
        })
        assert b.parse(line) is None

    def test_result_success(self):
        b = _backend()
        stats = {
            "total_tokens": 9300,
            "input_tokens": 9276,
            "output_tokens": 3,
            "cached": 0,
            "duration_ms": 2306,
            "tool_calls": 0,
        }
        line = self._line({"type": "result", "status": "success", "stats": stats})
        evt = b.parse(line)
        assert evt is not None
        assert evt.type == "result"
        assert evt.usage == stats
        assert evt.error is None

    def test_result_error_captures_prior_error_message(self):
        b = _backend()
        # First, an error event
        b.parse(self._line({
            "type": "error",
            "severity": "error",
            "message": "Invalid stream: malformed tool call.",
        }))
        # Then the result event
        stats = {"total_tokens": 100, "input_tokens": 90, "output_tokens": 10}
        line = self._line({"type": "result", "status": "error", "stats": stats})
        evt = b.parse(line)
        assert evt is not None
        assert evt.type == "result"
        assert evt.error is not None
        assert evt.error["message"] == "Invalid stream: malformed tool call."
        assert evt.error["subtype"] == "error"

    def test_result_error_captures_direct_result_error_message(self):
        b = _backend()
        stats = {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0}
        line = self._line({
            "type": "result",
            "status": "error",
            "error": {
                "type": "unknown",
                "message": "[API Error: An unknown error occurred.]",
            },
            "stats": stats,
        })
        evt = b.parse(line)
        assert evt is not None
        assert evt.type == "result"
        assert evt.usage == stats
        assert evt.error is not None
        assert evt.error["message"] == "[API Error: An unknown error occurred.]"
        assert evt.error["subtype"] == "unknown"

    def test_error_msg_cleared_after_result(self):
        b = _backend()
        b.parse(self._line({"type": "error", "message": "oops"}))
        b.parse(self._line({"type": "result", "status": "error", "stats": {}}))
        # Second error result with no preceding error event should have empty message
        line = self._line({"type": "result", "status": "error", "stats": {}})
        evt = b.parse(line)
        assert evt is not None
        assert evt.error["message"] == ""

    def test_error_event_alone_returns_none(self):
        b = _backend()
        line = self._line({"type": "error", "severity": "error", "message": "something went wrong"})
        assert b.parse(line) is None

    def test_result_success_has_no_session_id(self):
        b = _backend()
        line = self._line({"type": "result", "status": "success", "stats": {}})
        evt = b.parse(line)
        assert evt is not None
        assert evt.session_id == ""

    def test_invalid_json_ignored(self):
        b = _backend()
        assert b.parse("not json") is None

    def test_raw_preserved(self):
        b = _backend()
        line = self._line({"type": "init", "session_id": "x", "model": "m"})
        evt = b.parse(line)
        assert evt is not None
        assert evt.raw == line
