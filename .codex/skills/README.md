# Codex Skills (Local)

## When to use which skill
- python-api-stability-and-migrations: Changing interfaces or data contracts that have existing callers; use for deprecation, shims, and phased rollout.
- python-refactor-and-simplify: Targeted refactors that preserve behavior; use to reduce complexity without changing outputs.
- python-dependency-and-packaging-hygiene: Dependency grouping, version pinning, entry points, packaging ergonomics.
- python-performance-triage: Performance issues or suspected bottlenecks; use to add instrumentation and minimal fixes.
- python-architecture-review: Architecture and risks; use to identify hotspots and propose a roadmap.

## Overlap and selection guidance
- Refactor vs Architecture review:
  - Use architecture-review to map modules, risks, and a roadmap.
  - Use refactor-and-simplify to implement concrete changes within that roadmap.
- API stability vs Refactor:
  - If a refactor affects public/internal APIs, pair it with api-stability-and-migrations.
- Packaging hygiene vs Refactor:
  - Use packaging-hygiene when changes involve deps, entry points, or runtime ergonomics.
- Performance triage vs Refactor:
  - Use performance-triage first to gather evidence, then refactor only if a bottleneck is proven.

## Quick pairing patterns
- API change: api-stability-and-migrations + refactor-and-simplify
- Large design review: architecture-review (then refactor-and-simplify for the first step)
- Release readiness: dependency-and-packaging-hygiene + api-stability-and-migrations
- Performance fix: performance-triage (then refactor-and-simplify if needed)
