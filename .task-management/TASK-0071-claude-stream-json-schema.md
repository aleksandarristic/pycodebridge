# TASK-0071: Claude stream-json schema reference

Captured live from `claude 2.1.169` on 2026-06-09. Used to implement `ClaudeBackend.parse()`.

## CLI invocation

```
claude -p --output-format stream-json --verbose [flags] <prompt>
```

Key flags:
| Flag | Notes |
|------|-------|
| `-p` | Non-interactive / print mode (required) |
| `--output-format stream-json` | One JSON object per line on stdout |
| `--verbose` | Emit all event types (system, assistant, result, etc.) |
| `--resume <session_id>` | Resume by session ID (cross-session persistence) |
| `-c` / `--continue` | Resume most recent session in cwd |
| `--model <model>` | e.g. `claude-sonnet-4-6`, `opus`, `sonnet`, `haiku` |
| `--effort <level>` | `low`, `medium`, `high`, `xhigh`, `max` |
| `--add-dir <path>` | Grant tool access to a directory (use for repo_path) |
| `--permission-mode <mode>` | `default`, `acceptEdits`, `auto`, `bypassPermissions` |
| `--dangerously-skip-permissions` | Bypass all permission checks |

Prompt is passed as the last positional argument (subprocess-safe, no shell escaping needed via `subprocess_exec`).

## Event types (stdout, one JSON object per line)

### 1. `system` / `subtype: "init"`

First event(s) emitted. May appear multiple times for parallel subagent init.

```json
{
  "type": "system",
  "subtype": "init",
  "session_id": "d6dff65c-9c43-45db-8381-b786a30e3b94",
  "model": "claude-sonnet-4-6",
  "tools": ["Bash", "Edit", ...],
  "permissionMode": "default",
  "claude_code_version": "2.1.169",
  "uuid": "..."
}
```

**Parser action:** emit `NormalizedEvent(type="init", session_id=obj["session_id"])` — triggers `on_thread` in `base.py` which persists the session ID, enabling `--resume` on the next run.

### 2. `rate_limit_event`

```json
{
  "type": "rate_limit_event",
  "rate_limit_info": { "status": "allowed", "resetsAt": ..., "rateLimitType": "five_hour", ... },
  "uuid": "...",
  "session_id": "..."
}
```

**Parser action:** return `None` (ignorable).

### 3. `assistant`

Emitted once per model turn. May contain text output, tool calls, or thinking blocks.

```json
{
  "type": "assistant",
  "message": {
    "model": "claude-sonnet-4-6",
    "id": "msg_016Yx4MugeUzrL5FeLjXGJR3",
    "type": "message",
    "role": "assistant",
    "content": [
      { "type": "text", "text": "Hello!" },
      { "type": "thinking", "thinking": "..." },
      { "type": "tool_use", "id": "toolu_...", "name": "Bash", "input": { "command": "ls ..." } }
    ],
    "usage": {
      "input_tokens": 2,
      "cache_creation_input_tokens": 18069,
      "cache_read_input_tokens": 0,
      "output_tokens": 2,
      "service_tier": "standard"
    }
  },
  "session_id": "...",
  "uuid": "..."
}
```

**Parser action:** emit `NormalizedEvent(type="message", texts=[block["text"] for blocks with type=="text"])`. Do NOT include `usage` here — use the `result` event totals instead to avoid double-counting across turns.

### 4. `user`

Tool results sent back to the model. Not useful for output/usage purposes.

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      { "type": "tool_result", "tool_use_id": "toolu_...", "content": "...", "is_error": false }
    ]
  },
  "session_id": "...",
  "tool_use_result": { "stdout": "...", "stderr": "", "interrupted": false }
}
```

**Parser action:** return `None`.

### 5. `result` (final event)

Always the last event. Use this for usage accounting.

```json
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "result": "Hello!",
  "session_id": "d6dff65c-9c43-45db-8381-b786a30e3b94",
  "duration_ms": 2264,
  "num_turns": 1,
  "total_cost_usd": 0.068,
  "usage": {
    "input_tokens": 2,
    "cache_creation_input_tokens": 18069,
    "cache_read_input_tokens": 0,
    "output_tokens": 5,
    "server_tool_use": { "web_search_requests": 0 },
    "iterations": [...]
  }
}
```

Error case: `"subtype": "error"` and/or `"is_error": true`.

**Parser action:** emit `NormalizedEvent(type="result", session_id=..., usage=obj["usage"])`. If `is_error`, set `error={"message": obj.get("result",""), "subtype": obj.get("subtype")}`.

## NormalizedEvent mapping summary

| Stream-json event | NormalizedEvent.type | session_id | texts | usage | error |
|---|---|---|---|---|---|
| `system/init` | `"init"` | ✓ from `session_id` | — | — | — |
| `assistant` (text) | `"message"` | — | ✓ content[].type=="text" | — | — |
| `result` (success) | `"result"` | ✓ | — | ✓ full totals | — |
| `result` (error) | `"result"` | ✓ | — | ✓ | ✓ |
| everything else | `None` (skip) | — | — | — | — |

## Auth env vars (to add to env allowlist)

- `ANTHROPIC_API_KEY` — direct API key auth
- `CLAUDE_CODE_OAUTH_TOKEN` — OAuth token (headless/Docker)
- `CLAUDE_CONFIG_DIR` — path to mounted config directory

## Config block (to add to `config.py`)

```yaml
claude:
  binary: claude
  permission_mode: default   # default|acceptEdits|auto|bypassPermissions
  model: ""                  # empty = claude's default
  effort: ""                 # empty = claude's default
  env: {}
```
