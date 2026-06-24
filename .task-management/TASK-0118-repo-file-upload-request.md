# TASK-0118 — Verify and document repo file upload workflow

## Intent

Make the repo file upload workflow explicit and reliable for Discord users:
an operator should be able to attach one or more files, choose where they should
land in the active repo, and receive clear confirmation or rejection messages.

## Current signals

- Uploads are handled through attachment events rather than a text command.
- `FileTransferService.handle_upload_request()` collects attachments, applies
  per-file, total-size, and count limits, then asks the user for a repo-relative
  destination path.
- `FileTransferService.handle_pending_upload_response()` saves files after a
  path response and rejects path traversal, symlink parents, invalid filenames,
  and unsafe final paths.
- Existing tests reference upload behavior in
  `tests/test_dm_upload_download_gating.py`, `tests/test_dm_binding.py`, and
  `tests/test_integration_harness.py`.

## Scope

1. Verify the current upload UX end to end:
   - single attachment flow
   - multi-attachment directory flow
   - pending path prompt and response
   - expired pending upload
   - missing/invalid destination path
   - capability-disabled rejection
2. Confirm auth expectations match command/security docs (`upload` TOTP policy).
3. Confirm limits and error messages are clear:
   - `files.max_upload_mb`
   - `files.max_upload_total_mb`
   - `files.max_upload_count`
4. Update user-facing docs if anything is missing or ambiguous:
   - `README.md`
   - `docs/COMMAND_SURFACE.md`
   - command/help text or workflow docs, if needed
5. Add or adjust focused tests only where coverage is missing.

## Acceptance Criteria

- A user can upload one file to a repo-relative file path.
- A user can upload multiple files to a repo-relative directory path.
- Unsafe paths and symlink-based writes are rejected without writing outside the
  repo.
- Upload limits and auth requirements are documented consistently.
- Targeted upload-related tests pass.

## Suggested validation

```sh
./.venv/bin/pytest -q tests/test_dm_upload_download_gating.py
./.venv/bin/pytest -q tests/test_dm_binding.py -k upload
./.venv/bin/pytest -q tests/test_integration_harness.py -k upload
```
