---
name: python-refactor-and-simplify
description: Refactor and simplify Python code in a moderately complex repository while preserving behavior, matching existing intent, and improving maintainability/performance where justified.
metadata:
  focus: refactor,simplify,maintainability,performance,scalability
---

## Purpose
Make targeted refactors that reduce complexity and future-proof a Python codebase without changing externally observable behavior unless explicitly requested.

## Operating principles
- Preserve behavior by default. If behavior must change, call it out explicitly and minimize blast radius.
- Prefer small, reviewable changes over large rewrites.
- Match existing repo conventions (style, typing, logging, error handling, structure).
- Avoid speculative architecture. Justify non-trivial changes with concrete repo evidence.
- Optimize for: correctness > clarity > maintainability > performance.

## Step 1 — Establish understanding (mandatory)
Before making changes, identify:
1) Entry points (CLI, `__main__`, service runners), primary workflows, and critical modules.
2) Code ownership boundaries: core domain logic vs adapters (I/O, HTTP, DB, queue, CLI).
3) Existing conventions: config patterns, dependency injection, async model, logging, error handling.
4) Risks: implicit coupling, circular imports, shared mutable state, hidden global config, monkeypatching.

If intent is unclear, locate and cite the repo's authoritative documents (README/AGENTS/docs). If still unclear, stop and ask a focused question rather than guessing.

## Step 2 — Build a refactor plan (mandatory)
Produce a plan with:
- Goals (what improves and how you will measure it)
- Non-goals (what you will not touch)
- Scope boundaries (files/modules/packages)
- Risk assessment (what could break, how to detect regressions)
- Rollout strategy (sequence of commits)

## Step 3 — Identify high-leverage refactors
Prioritize changes that deliver high value with low risk:
- Reduce duplicated logic and inconsistent utilities
- Untangle responsibilities (domain vs I/O)
- Replace implicit global state with explicit parameters/context objects
- Normalize error paths and exception boundaries
- Introduce typed dataclasses / small interfaces for cross-module contracts
- Improve performance only where a bottleneck is evidenced (hot paths, excessive I/O, repeated parsing)

## Step 4 — Execute with guardrails
When implementing:
- Prefer diffs; avoid full-file rewrites unless necessary.
- Keep functions small; remove nesting; flatten control flow where it improves clarity.
- Prefer pure functions and explicit dependencies.
- Introduce internal APIs with stable, typed boundaries.
- Make naming consistent and descriptive.
- Add or update tests matching existing test style (or explain why not feasible).
- Run linters/tests if available; do not assume they exist.

## Step 5 — Performance and scalability considerations
Only propose/implement performance work when justified by repo evidence:
- Replace O(n^2) scans, repeated regex compilation, repeated JSON/YAML loads
- Move expensive I/O out of loops; batch where appropriate
- Prefer streaming over buffering for large outputs
- Avoid unnecessary concurrency; use it only when the workload benefits

## Output requirements
- Provide:
  1) A short understanding summary (repo intent + key flows)
  2) A refactor plan (bulleted, ordered)
  3) The patch/diff for the first incremental step
  4) How to validate (commands/tests/manual checks)
- Explicitly list assumptions and unknowns.
- If the best action is “no refactor needed,” say so and explain.

## Refusal / stop conditions
Stop and ask for guidance if:
- The change would alter public API/behavior and requirements are unclear
- There is no way to validate behavior and risk is high
- The refactor requires major re-architecture without a clear goal
