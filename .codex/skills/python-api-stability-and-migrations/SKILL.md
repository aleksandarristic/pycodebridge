---
name: python-api-stability-and-migrations
description: Evolve internal/public APIs safely using deprecations, adapters, and incremental migrations.
---

## Principles
- Preserve external contracts by default.
- Introduce new API alongside old; deprecate with warnings.
- Provide adapters/shims to keep callers working.
- Remove old API only when migration is complete.

## Output
- Contract summary (what must not break)
- Migration plan (phased)
- Minimal initial patch (add new API + adapter)
- Deprecation notes and tests
