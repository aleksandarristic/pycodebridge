# Router Refactor Plan

The current router (`codebridge/routing/router.py`) is too large and mixes
concerns (transport normalization, auth, command parsing, execution orchestration,
state mutations, formatting). This plan decomposes the router into focused modules
with a hard requirement: no long-term compatibility shims.

## Goals

1. Reduce cognitive load and review surface by separating concerns.
2. Keep behavior transport-agnostic at the boundaries (`MessageEvent` / `ResponseSink`).
3. Keep feature parity while moving logic out of the monolithic router file.
4. End with a single canonical router module path and updated tests/imports.

## Non-goals

- No user-facing behavior changes unless explicitly scoped and tested.
- No parallel old/new router runtime paths after migration completes.
- No persistent compatibility import aliases once cutover is done.

## Target architecture

Proposed package layout (under `codebridge/routing/`):

1. `router.py`
   - Small composition root only.
   - Wires collaborators and delegates to command services.
2. `event_context.py`
   - Event normalization (including Discord thread room-key normalization).
   - Sink contextualization (`thread`, `reply`, chunking, lock-prefix).
3. `authz.py`
   - TOTP verification, unlock windows/scopes, rate limiting, command gating.
4. `commands.py`
   - Command normalization/parsing and command dispatch coordination.
5. `sessions.py`
   - Session selection, sticky behavior, state updates, pending-input/session lookups.
6. `runs.py`
   - `run_codex` orchestration, heartbeat/completion reporting, compatibility retry.
7. `ops.py`
   - Operator/admin surfaces (`status`, `health`, `options`, `budget`, `audit`).
8. `presenters.py`
   - Message rendering/formatting helpers for status/help/options/budget outputs.

The result is a thin `Router` that orchestrates collaborators instead of owning
all detailed logic.

## Dependency rules

1. `router.py` may depend on all router submodules.
2. Submodules must not import `router.py`.
3. Submodules can share stable contracts via dedicated data classes/protocols.
4. Keep transport adapters outside router internals.

## Migration phases

### Phase 0: Baseline and guardrails

- Keep current tests green as baseline.
- Add/refine integration tests for thread scoping, run args, and auth gating.
- Add architecture docs (this plan + testing map).

### Phase 1: Extract event/sink context

- Move event normalization and sink wrappers into `event_context.py`.
- Keep behavior exactly equivalent.
- Update unit tests to import/use the new module directly.

Exit criteria:
- `Router.handle_message` no longer directly implements thread/reply/chunk/lock wrapping.

### Phase 2: Extract authz/TOTP

- Move command-gating and TOTP unlock logic to `authz.py`.
- Keep data ownership explicit (unlock windows, limiter, replay guard).
- Add/adjust tests to target `authz.py` directly where possible.

Exit criteria:
- Router only calls `authz.requires_totp(...)` and `authz.verify(...)`.

### Phase 3: Extract command parse/dispatch pipeline

- Move shortcut normalization and command parsing to `commands.py`.
- Keep a clear parse result object (command, rest, session hints, prompt forms).
- Remove duplicate parsing branches in router.

Exit criteria:
- Router has one parse call and one dispatch call.

### Phase 4: Extract run orchestration

- Move `run_codex`, retry compatibility, heartbeat/completion to `runs.py`.
- Keep audit append/error-log behavior in that module.
- Unit test retry/arg transformations at module level.

Exit criteria:
- Router no longer contains process lifecycle loops.

### Phase 5: Extract status/options/budget/audit presentation and handlers

- Move text rendering into `presenters.py`.
- Keep command handlers in `ops.py`.
- Limit router to selecting handler + passing context.

Exit criteria:
- Router has no large string rendering functions.

### Phase 6: Cutover and cleanup (no shims)

- Remove temporary compatibility imports/re-export files.
- Keep only one canonical import path for router internals.
- Update all tests/imports to use final module locations.
- Delete dead methods from old monolithic router.

Exit criteria:
- No shim modules, no deprecated aliases, no dual runtime paths.
- `codebridge/routing/router.py` is orchestration-only (target < 400 LOC).

## Test migration plan

1. Keep `tests/test_integration_harness.py` for black-box behavior.
2. Split monolithic router-unit coverage by concern:
   - `tests/test_event_context.py`
   - `tests/test_authz.py`
   - `tests/test_commands_pipeline.py`
   - `tests/test_runs.py`
   - `tests/test_ops_presenters.py`
3. Update existing router tests to import new modules directly.
4. Remove tests that only validate transitional shims.

## Proposed execution order (PR tracks)

1. Track A: `event_context.py` extraction + tests.
2. Track B: `authz.py` extraction + tests.
3. Track C: `commands.py` extraction + tests.
4. Track D: `runs.py` extraction + tests.
5. Track E: `ops.py` + `presenters.py` extraction + tests.
6. Track F: final cutover and dead-code/shim removal.

Each track should keep `pytest -q` green and be independently reviewable.

## Risks and mitigations

1. Behavior drift in command gating:
   - Mitigation: preserve integration harness as source-of-truth behavior tests.
2. Hidden coupling via shared mutable router state:
   - Mitigation: define explicit state objects passed to extracted modules.
3. Retry/orchestration regressions:
   - Mitigation: keep explicit regression tests for args/retry and stderr failure paths.

## Definition of done

1. Router decomposition complete with clear module boundaries above.
2. No compatibility shims/import aliases remain.
3. All router-related tests use final module locations.
4. Full suite passes and docs are updated (`README.md`, `docs/TESTING.md`, this plan).
