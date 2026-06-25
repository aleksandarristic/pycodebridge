# TASK-0117 — Verify and document repo file download request workflow

**Status:** DONE

## Intent

Make the repo file download workflow explicit and reliable for Discord users:
an operator should be able to request a file from the active repo and receive it
as a Discord attachment.

## Current signals

- `!c download <path>` and alias `!c dl <path>` are already registered in
  `codebridge/commands/registry.py`.
- `FileTransferService.handle_download()` already gates on transport download
  capability and sends files through `ResponseSink.send_file()`.
- Existing tests reference download behavior in
  `tests/test_dm_upload_download_gating.py` and `tests/test_integration_harness.py`.

## Scope

1. Verify the current command UX end to end:
   - `!c download <path>`
   - `!c dl <path>`
   - missing path usage text
   - missing file / directory / path traversal rejection
   - Discord download capability disabled
2. Confirm auth expectations match command docs (`unlock/default`).
3. Update user-facing docs if anything is missing or ambiguous:
   - `README.md`
   - `docs/COMMAND_SURFACE.md`
   - command help text, if needed
4. Add or adjust focused tests only where coverage is missing.

## Acceptance Criteria

- A user can request a repo-relative file path and receive the file attachment
  without exposing paths outside the repo.
- Error messages are concise and actionable for bad input.
- Command docs and help mention the `download` / `dl` flow consistently.
- Targeted download-related tests pass.

## Suggested validation

```sh
./.venv/bin/pytest -q tests/test_dm_upload_download_gating.py
./.venv/bin/pytest -q tests/test_integration_harness.py -k download
```
