from codebridge.status_parse import parse_status_lines, format_status_summary

SAMPLE_OUTPUT = """/status

╭────────────────────────────────────────────────────────────────────────────╮
│  >_ OpenAI Codex (v0.92.0)                                                 │
│                                                                            │
│ Visit https://chatgpt.com/codex/settings/usage for up-to-date              │
│ information on rate limits and credits                                     │
│                                                                            │
│  Model:            gpt-5.1-codex-mini (reasoning medium, summaries auto)   │
│  Directory:        ~/Code/pycodebridge                                     │
│  Approval:         on-request                                              │
│  Sandbox:          workspace-write                                         │
│  Agents.md:        AGENTS.md                                               │
│  Account:          user@example.com (Plus)                                  │
│  Session:          00000000-0000-0000-0000-000000000000                    │
│                                                                            │
│  Context window:   75% left (74.5K used / 258K)                            │
│  5h limit:         [███████████░░░░░░░░░] 57% left (resets 16:04)          │
│  Weekly limit:     [█████░░░░░░░░░░░░░░░] 27% left (resets 08:19 on 5 Feb) │
╰────────────────────────────────────────────────────────────────────────────╯"""


class TestStatusParse:
    def test_parses_key_fields(self):
        lines = SAMPLE_OUTPUT.splitlines()
        summary = parse_status_lines(lines)
        assert "Model" in summary.fields
        assert summary.model == "gpt-5.1-codex-mini (reasoning medium, summaries auto)"
        assert summary.directory == "~/Code/pycodebridge"
        assert summary.context_window == "75% left (74.5K used / 258K)"
        assert summary.five_hour_limit.startswith("[████")
        assert "reset" in summary.weekly_limit.lower()

    def test_format_lines_prioritizes_key_fields(self):
        summary = parse_status_lines(SAMPLE_OUTPUT.splitlines())
        lines = format_status_summary(summary)
        assert lines[0].startswith("Model:")
        assert any("Context window" in line for line in lines)
        assert any("5h limit" in line for line in lines)
        assert any("Weekly limit" in line for line in lines)

    def test_handles_unknown_lines_gracefully(self):
        summary = parse_status_lines(["Extra line without colon", "Key: value"])
        assert summary.fields.get("Key") == "value"
        assert "Extra line" not in summary.fields
