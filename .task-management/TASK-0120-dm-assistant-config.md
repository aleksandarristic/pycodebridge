# TASK-0120 — DM assistant: config section

**Status:** DONE

## Intent

Add a `dm_assistant` config section that controls the LLM-powered DM
assistant feature.

## Scope

- Add `DmAssistantConfig` dataclass with fields:
  - `enabled` (default `false`)
  - `default_backend` (default `""` — falls back to `agent.default_backend`)
  - `model` (default `""`)
  - `effort` (default `""`)
  - `memory_dir` (default `""` — falls back to `{state.data_dir}/dm-memory/`)
  - `start_prompt` (default template — see TASK-0122)
- Wire into top-level `Config`.
- Update `config.example.yaml` and `config.docker.example.yaml` with
  commented-out `dm_assistant` block.
- Add config tests.

## Acceptance Criteria

- `dm_assistant.enabled: false` keeps current DM behaviour unchanged.
- All fields parse and apply defaults correctly.
- Config tests pass.
