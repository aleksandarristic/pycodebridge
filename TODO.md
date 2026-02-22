# TODO (Public)

Current status:

TODO (Near-term):

- Improve long-run job UX in Discord.
  - Add periodic progress heartbeat and concise completion summary (files touched, tests run, key result).
- Add session lifecycle controls.
  - Support idle session expiry, archive/summary output, and easy restore/start-from-summary flow.
- Add usage budget visibility and controls.
  - Track token/cost usage per user/channel with configurable soft/hard thresholds.
- Expand audit trail UX commands.
  - Add easier `audit` lookup/filter commands and a downloadable artifact bundle for a job/session.
- Add safer write-operation workflow.
  - Introduce explicit confirmation flow for destructive/high-impact actions (for example push/delete/rename paths).

Backlog:

- Role-based permissions model (Discord-role driven access tiers).
- Per-channel policy configuration (command/model/runtime policy by channel).
- Knowledge shortcuts/macros for repeatable repo workflows.
- Web-based/dashboard features (status/admin web surface, browser ops views).
