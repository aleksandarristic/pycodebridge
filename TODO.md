# TODO (Public)

Current status:

- Task 2: Stronger job/session observability
  - Add per-job timestamps (`queued_at`, `started_at`, `ended_at`) and surface them in `!c ps` and `!c logs`.

- Task 6: Help/UX discoverability
  - Add concise "related commands" hints in key responses (for example `status` should point to `!ps`/`!w` when relevant).

- Task 8: Safer automation around git/gh
  - Add optional guardrails for dangerous git operations (`push --force`, branch delete) with explicit confirmation flow.

- Task 9: Operational health endpoint
  - Add a lightweight health/metrics HTTP endpoint for uptime checks (queue depth, active sessions, recent errors).
