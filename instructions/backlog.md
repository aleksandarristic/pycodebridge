# Backlog

This backlog holds longer-term items that can generate future tasks in `instructions/tasks.md`.
Promote items from here into the active task list when ready to schedule work.

31) TODO - Slack adapter implementation (backlog)
- Owner: TBD
- Subtasks:
  - Define Slack config schema (tokens/signing secret/app settings) and validation in `codebridge/config.py`.
  - Implement Slack adapter runtime wiring (event ingestion, response send, typing).
  - Add upload/download support for Slack if supported; otherwise guard via capabilities.
  - Add adapter integration tests with mocked Slack payloads.

35) TODO - Google Chat adapter implementation (backlog)
- Owner: TBD
- Subtasks:
  - Define Google Chat config schema (credentials/webhook) and validation.
  - Implement adapter mapping for events + responses (MessageEvent + ResponseSink).
  - Add thread id mapping + reply targeting where supported.
  - Add integration tests with mocked payloads.

36) TODO - Microsoft Teams adapter implementation (backlog)
- Owner: TBD
- Subtasks:
  - Define Teams config schema (bot credentials/app settings) and validation.
  - Implement adapter mapping for events + responses (MessageEvent + ResponseSink).
  - Add thread/conversation id mapping + reply targeting.
  - Add integration tests with mocked payloads.

46) TODO - Threaded replies for Slack/Teams/Google Chat (backlog)
- Owner: TBD
- Subtasks:
  - Add thread id extraction in Slack/Teams/Chat adapters.
  - Implement threaded send/reply behavior in corresponding ResponseSinks.
  - Add adapter tests to assert thread targeting behavior.
