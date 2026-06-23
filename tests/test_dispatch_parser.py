"""Tests for codebridge.dispatch.parser."""

import pytest
from codebridge.dispatch.parser import parse_dispatch, DispatchSpec


def test_single_codex():
    spec = parse_dispatch("@codex implement auth")
    assert spec is not None
    assert spec.agents == ["codex"]
    assert spec.is_fanout is False
    assert spec.is_orchestrated is False
    assert spec.prompt == "implement auth"


def test_single_claude_not_orchestrated():
    spec = parse_dispatch("@claude review this")
    assert spec is not None
    assert spec.agents == ["claude"]
    assert spec.is_orchestrated is False
    assert spec.is_fanout is False


def test_claude_plus_codex_orchestrated():
    spec = parse_dispatch("@claude @codex implement auth")
    assert spec is not None
    assert spec.agents == ["claude", "codex"]
    assert spec.is_orchestrated is True
    assert spec.is_fanout is True
    assert spec.prompt == "implement auth"


def test_codex_plus_gemini_fanout_not_orchestrated():
    spec = parse_dispatch("@codex @gemini build UI")
    assert spec is not None
    assert spec.agents == ["codex", "gemini"]
    assert spec.is_fanout is True
    assert spec.is_orchestrated is False
    assert spec.prompt == "build UI"


def test_orchestrated_three_agents():
    spec = parse_dispatch("@claude plan this, dispatch @codex and @gemini")
    assert spec is not None
    assert spec.agents == ["claude", "codex", "gemini"]
    assert spec.is_orchestrated is True
    assert spec.is_fanout is True
    # known mentions are stripped; remaining text is kept
    assert "plan this" in spec.prompt
    assert "dispatch" in spec.prompt


def test_no_mentions_returns_none():
    assert parse_dispatch("no mentions here") is None
    assert parse_dispatch("") is None
    assert parse_dispatch("implement the thing") is None


def test_mixed_case_normalised():
    spec = parse_dispatch("@Codex implement")
    assert spec is not None
    assert spec.agents == ["codex"]


def test_unknown_at_mention_left_in_prompt():
    spec = parse_dispatch("@foo bar @codex do it")
    assert spec is not None
    assert spec.agents == ["codex"]
    assert "@foo" in spec.prompt
    assert "bar" in spec.prompt
    assert "do it" in spec.prompt


def test_agent_substrings_inside_emails_do_not_dispatch():
    assert parse_dispatch("email user@codex.com about auth") is None
    assert parse_dispatch("send this to ops@gemini.dev") is None


def test_agent_substrings_inside_words_do_not_dispatch():
    assert parse_dispatch("use foo@codex for the config key") is None
    assert parse_dispatch("set name=@claude-review in config") is None
    assert parse_dispatch("look at @gemini-cli behavior") is None


def test_agent_mentions_allow_punctuation_boundaries():
    spec = parse_dispatch("(@codex), please implement auth")
    assert spec is not None
    assert spec.agents == ["codex"]
    assert spec.prompt == "(), please implement auth"


def test_duplicate_agent_deduplicated():
    spec = parse_dispatch("@codex @codex implement")
    assert spec is not None
    assert spec.agents == ["codex"]
    assert spec.is_fanout is False


def test_raw_preserved():
    msg = "@claude @codex do the thing"
    spec = parse_dispatch(msg)
    assert spec is not None
    assert spec.raw == msg


def test_prompt_only_at_mentions():
    spec = parse_dispatch("@codex")
    assert spec is not None
    assert spec.prompt == ""


def test_order_preserved():
    spec = parse_dispatch("@gemini @claude @codex some task")
    assert spec is not None
    assert spec.agents == ["gemini", "claude", "codex"]
    # claude is present but not first, so not orchestrated by position;
    # orchestrated is true whenever claude + others
    assert spec.is_orchestrated is True
