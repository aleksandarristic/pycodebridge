# TASK-0119 — Make file-transfer TOTP enforcement configurable

## Intent

Allow operators to disable TOTP for repo file upload/download workflows without
turning off TOTP globally or weakening other command groups.

## Scope

- Add a `discord.totp.command_groups.file_transfer` boolean config option.
- Default to the existing protected behavior.
- When disabled:
  - uploads do not require TOTP for attachment submit or upload-path response
  - `download` does not require TOTP/default unlock
- Keep `git`, `gh`, and high-risk command group behavior unchanged.
- Update config examples and user-facing docs.
- Add focused config and router integration tests.

## Acceptance Criteria

- `file_transfer: true` preserves existing upload/download TOTP behavior.
- `file_transfer: false` allows uploads/downloads while global TOTP remains
  enabled for other protected commands.
- Targeted config and file-transfer auth tests pass.
