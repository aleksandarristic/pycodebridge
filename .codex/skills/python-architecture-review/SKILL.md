---
name: python-architecture-review
description: Review repository architecture, identify hotspots and risks, and propose a prioritized improvement roadmap.
---

## Method
- Identify core domain logic vs adapters (I/O boundaries).
- Map dependencies and coupling (imports, shared state, cross-module reach).
- Highlight scaling concerns: contention points, serialization, synchronous bottlenecks, excessive I/O, memory growth.
- Highlight maintainability concerns: inconsistent patterns, unclear ownership, duplicated logic, brittle configuration.
- Provide a prioritized roadmap: quick wins, medium refactors, larger projects.

## Output
- Architecture summary (modules + responsibilities)
- Top risks (with file/module references)
- Roadmap with 3 tiers: 1–2 day, 1–2 week, 1–2 month
- Validation plan per tier
