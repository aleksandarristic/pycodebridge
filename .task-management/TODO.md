# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks

- [TASK-0129] Add first-class Gemini API key configuration.
  - Requested: 2026-06-26.
  - Goal: support Gemini CLI/API-key authentication through bridge config without requiring operators to hand-edit `gemini.env` for the common case.
  - Proposed approach:
    - Add a dedicated Gemini auth config field such as `gemini.api_key_env` with default `GEMINI_API_KEY`.
    - Resolve the actual secret from the host environment at runtime instead of storing the raw API key in YAML.
    - Merge the resolved key into Gemini backend env construction alongside existing Gemini auth env vars.
    - Keep `gemini.env` as an escape hatch for advanced cases, but prefer the dedicated field in docs/examples.
  - Constraints:
    - Do not encourage storing plaintext API keys directly in tracked config files.
    - Preserve compatibility for existing OAuth / ADC-based Gemini setups.
    - Fail clearly when Gemini is selected but the configured API key env var is missing.
  - Relevant code:
    - `codebridge/config.py` (`GeminiConfig` parsing/defaults).
    - `codebridge/agents/gemini.py` and shared backend env merge path.
    - `codebridge/agents/factory.py` for backend construction.
    - `README.md` / `config.example.yaml` for operator docs.
  - Acceptance criteria:
    - Operators can configure the Gemini API key env var name in YAML.
    - The bridge injects that env var value for Gemini runs without requiring `gemini.env.GEMINI_API_KEY`.
    - Missing-key failures are actionable and identify the expected env var name.
    - Docs and focused config/backend tests cover the new path.
