# Testing Guide

This document explains what each test file is responsible for and where to
add new tests without duplicating coverage.

## Test strategy

The suite is intentionally layered:

1. Unit tests validate pure helpers, parser behavior, and small service logic.
2. Adapter/contract tests validate platform normalization and sink capability behavior.
3. Integration harness tests validate command routing behavior across multiple subsystems.

When adding tests, place them in the narrowest layer that can prove the behavior.

## Fast test commands

```bash
# Full suite
.venv/bin/python -m pytest -q

# Router integration harness only
.venv/bin/python -m pytest -q tests/test_integration_harness.py

# Router-focused unit surface
.venv/bin/python -m pytest -q tests/test_router_*.py tests/test_thread_context.py
```

## File map: what each test file validates

### Core config/state/session plumbing

- `tests/test_config.py`: config load/validation/defaulting, env expansion, and invalid config failure cases.
- `tests/test_state.py`: persisted state serialization/deserialization and runtime option normalization.
- `tests/test_session_service.py`: session state lifecycle behavior and sticky/session metadata updates.
- `tests/test_session_coordinator.py`: active-process bookkeeping, queue handoff, and conflict tracking.
- `tests/test_queue.py`: per-channel queue ordering and running/queued status transitions.
- `tests/test_path.py`: repo name/path normalization and containment safety.

### Codex invocation and parser behavior

- `tests/test_codex.py`: Codex CLI arg construction and JSON/event text extraction behavior.
- `tests/test_model_commands.py`: model/model-reasoning command surface behavior and dispatch output.
- `tests/test_run_control_reporting.py`: run-control completion/heartbeat reporting semantics.

### Router-focused unit coverage

- `tests/test_router_helpers.py`: utility helper functions used by router commands.
- `tests/test_router_contextual_sink.py`: thread/reply/lock/chunk wrapper composition and behavior.
- `tests/test_router_status.py`: status rendering and session line formatting behavior.
- `tests/test_router_config.py`: `!c config` text rendering from current config.
- `tests/test_thread_context.py`: contextual thread sink behavior for message/file sends.
- `tests/test_command_parse.py`: low-level command and shortcut parse routines.
- `tests/test_command_registry.py`: command registration metadata and dispatch behavior.

### Transport adapters and contract tests

- `tests/test_transport.py`: MessageEvent/ResponseSink protocol-level assumptions.
- `tests/test_capabilities.py`: capability gating behavior for transport sinks.
- `tests/test_adapter_contracts.py`: adapter-level invariants.
- `tests/test_discord_adapter.py`: discord.py event/sink normalization behavior.
- `tests/test_discord_bot.py`: Discord bot lifecycle dispatch and guild-lock behaviors.
- `tests/fixtures_adapter_payloads.py`: adapter fixture data used by adapter contract tests.

### Command helper modules

- `tests/test_git_helpers.py`: safe git helper command filtering and command behavior.
- `tests/test_gh_helpers.py`: GitHub CLI helper command behavior and gating.
- `tests/test_git_bootstrap.py`: git bootstrap setup behavior and fallback handling.
- `tests/test_system_helpers.py`: health/updates helper rendering and error summarization.
- `tests/test_reply_helpers.py`: reply formatting/chunk behavior and forbidden formatting.
- `tests/test_health.py`: HTTP health endpoint payload and server behavior.

### DM admin and auth/security behavior

- `tests/test_dm_binding.py`: DM binding flow, commands, and reset behavior.
- `tests/test_dm_admin_repo_lifecycle.py`: DM-admin repo create/clone/copy/delete lifecycle paths.
- `tests/test_dm_upload_download_gating.py`: DM upload/download gating and auth requirements.
- `tests/test_audit.py`: audit file layout and summary scanning behavior.
- `tests/test_audit_helpers.py`: audit helper wrappers and failure handling.
- `tests/test_audit_redaction.py`: configured redaction pattern behavior.

### End-to-end integration harness

- `tests/test_integration_harness.py`: full Router behavior contracts across:
  - start/resume/stop lifecycle
  - Discord thread room scoping and parent channel mapping
  - command shortcuts and relay behavior
  - runtime options persistence and visibility
  - session expiration and conflict resolution
  - budget, audit, and help command surfaces
  - TOTP unlock/lock scope semantics and cooldown behavior
  - compatibility/retry argument regression coverage

## Integration harness section map

`tests/test_integration_harness.py` is large by design; tests are grouped using
header comments. Add new tests next to the closest existing behavior group:

1. Core lifecycle and room/thread scoping
2. Transport privacy and identity gating
3. Repo/session/run-control flows and shortcuts
4. Runtime options/lifecycle persistence/operator visibility
5. Session expiration/budgets/audit surfaces
6. Help/chunking/transport-specific reply behavior
7. TOTP authorization model
8. Local router regression checks

## Conventions for new tests

- Prefer explicit names of the form `test_<surface>_<expected_behavior>`.
- For regression fixes, include a narrow failing case plus one neighboring case
  to guard against overfitting.
- Keep fake collaborators deterministic; avoid sleeping except for queue polling
  loops that already exist in the harness.
- Add comments only where the intent is non-obvious or where the test encodes
  a contract that has regressed before.
