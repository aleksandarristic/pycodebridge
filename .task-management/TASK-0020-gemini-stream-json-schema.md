# TASK-0020: Gemini CLI stream-json schema reference

Captured live from `gemini 0.45.2` on 2026-06-09. Used to implement `GeminiBackend.parse()`.

## CLI invocation

```
gemini -o stream-json --skip-trust [flags] -p <prompt>
```

Key flags:
| Flag | Notes |
|------|-------|
| `-p "prompt"` | Non-interactive / print mode (required for headless) |
| `-o stream-json` | One JSON object per line on stdout |
| `--skip-trust` | Trust the cwd for this session (required for headless) |
| `--resume <session_id>` | Resume by session UUID |
| `--resume latest` | Resume the most recent session in cwd |
| `-m <model>` | e.g. `gemini-2.5-flash`, `gemini-2.5-pro` |
| `--approval-mode <mode>` | `default`, `auto_edit`, `yolo`, `plan` |
| `--yolo` | Shorthand for `--approval-mode yolo` |

Prompt is passed as the **value** of `-p`, not as a positional arg (unlike Claude).
Working directory is controlled by `cwd` at subprocess launch; no `--add-dir` equivalent needed.

## Event types (stdout, one JSON object per line)

### 1. `init`

First event. Emitted once per session start.

```json
{
  "type": "init",
  "timestamp": "2026-06-09T09:03:40.391Z",
  "session_id": "29ac53c5-4292-45fb-b133-b9f6ef6d8c6f",
  "model": "gemini-2.5-flash"
}
```

**Parser action:** emit `NormalizedEvent(type="init", session_id=obj["session_id"])`.

### 2. `message` (user echo)

```json
{
  "type": "message",
  "timestamp": "...",
  "role": "user",
  "content": "say hello in exactly three words"
}
```

**Parser action:** return `None` (ignorable echo of user input).

### 3. `message` (assistant)

```json
{
  "type": "message",
  "timestamp": "...",
  "role": "assistant",
  "content": "Hello there!",
  "delta": true
}
```

**Parser action:** emit `NormalizedEvent(type="message", texts=[obj["content"]])`.

### 4. `tool_use`

```json
{
  "type": "tool_use",
  "timestamp": "...",
  "tool_name": "run_shell_command",
  "tool_id": "run_shell_command__run_shell_command_..._0",
  "parameters": { "description": "...", "command": "ls -F /tmp" }
}
```

**Parser action:** return `None`.

### 5. `tool_result`

```json
{
  "type": "tool_result",
  "timestamp": "...",
  "tool_id": "run_shell_command__run_shell_command_..._0",
  "status": "success",
  "output": "/tmp@"
}
```

**Parser action:** return `None`.

### 6. `error`

Emitted before a `result` with `status: "error"`.

```json
{
  "type": "error",
  "timestamp": "...",
  "severity": "error",
  "message": "Invalid stream: The model returned an empty response or malformed tool call."
}
```

**Parser action:** stash `obj["message"]` in `_last_error_msg`; return `None`.

### 7. `result` (final event)

Always the last event. `stats` is the usage totals.

```json
{
  "type": "result",
  "timestamp": "...",
  "status": "success",
  "stats": {
    "total_tokens": 9300,
    "input_tokens": 9276,
    "output_tokens": 3,
    "cached": 0,
    "input": 9276,
    "duration_ms": 2306,
    "tool_calls": 0,
    "models": {
      "gemini-2.5-flash": {
        "total_tokens": 9300,
        "input_tokens": 9276,
        "output_tokens": 3,
        "cached": 0,
        "input": 9276
      }
    }
  }
}
```

Error case: `"status": "error"`. No error message in the result itself — it lives in the preceding `error` event.

**Parser action:** emit `NormalizedEvent(type="result", usage=obj["stats"])`.
If `status == "error"`, also set `error={"message": _last_error_msg, "subtype": "error"}` and clear `_last_error_msg`.

Note: no `session_id` in the `result` event (unlike Claude). Session ID only in `init`.

## NormalizedEvent mapping summary

| Stream-json event | NormalizedEvent.type | session_id | texts | usage | error |
|---|---|---|---|---|---|
| `init` | `"init"` | ✓ from `session_id` | — | — | — |
| `message` (role=assistant) | `"message"` | — | ✓ `[content]` | — | — |
| `result` (status=success) | `"result"` | — | — | ✓ full `stats` | — |
| `result` (status=error) | `"result"` | — | — | ✓ | ✓ from prior `error` event |
| everything else | `None` (skip) | — | — | — | — |

## stats vs usage field names

Gemini uses `stats` (not `usage`). Field names are compatible with `usage_from_event`:
- `stats.input_tokens` → `UsageStats.input_tokens`
- `stats.output_tokens` → `UsageStats.output_tokens`
- `stats.total_tokens` → `UsageStats.total_tokens`
- `stats.cached` → not yet surfaced (different from Claude's `cache_read_input_tokens`)

## Auth env vars (to add to env allowlist)

- `GEMINI_API_KEY` — direct API key auth
- `GOOGLE_APPLICATION_CREDENTIALS` — service account JSON path
- `GOOGLE_CLOUD_PROJECT` — GCP project for billing
- `GEMINI_CLI_TRUST_WORKSPACE` — alternative to `--skip-trust` (env var approach)

## Config block (in `config.py`)

```yaml
gemini:
  binary: gemini
  approval_mode: yolo   # default|auto_edit|yolo|plan
  model: ""             # empty = gemini's default (gemini-3-flash-preview at time of writing)
  env: {}
```
