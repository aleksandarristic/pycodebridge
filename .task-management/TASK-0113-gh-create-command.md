# TASK-0113 — `!c gh-create` command: check existing GH repo, create if absent, add remote

**Status:** TODO

## Goal

Give users a single command to wire a local repo to GitHub end-to-end:
check whether the GitHub repo already exists, create it if not, then add
`origin` as a remote. After this, `!c done --pr` works without any manual setup.

---

## Changes

### `codebridge/commands/registry.py`

Add a new `CommandSpec`:
```python
CommandSpec(
    "gh-create",
    "gh-create [--public]",
    "create GitHub repo for this channel (if absent) and wire remote",
    "Repo lifecycle",
    _cmd_gh_create,
    AUTH_UNLOCK_GH,
)
```

Add handler `_cmd_gh_create`:
1. Resolve `repo_name` and `repo_path` from the channel (already available as
   handler args).
2. Check if remote `origin` already exists:
   ```
   git remote get-url origin
   ```
   If it does, reply with the URL and return — nothing to do.
3. Check if the GitHub repo exists:
   ```
   gh repo view <owner>/<repo_name>
   ```
   If it exists, wire the remote:
   ```
   git remote add origin <ssh_or_https_url>
   git fetch origin
   ```
   Reply: "Remote wired to existing GitHub repo."
4. If it does not exist, create it:
   ```
   gh repo create <repo_name> --private --source . --remote origin --push
   ```
   (Use `--public` flag if user passed `--public`.)
   Reply: "GitHub repo created and remote wired."

**Auth:** `AUTH_UNLOCK_GH` — same as `!c gh` passthrough, requires gh unlock.

**Error handling:**
- `gh` not installed or not authenticated → friendly error
- repo_path doesn't have git init → tell user to run `!c create` first
- `gh repo create` fails → surface stderr

### `codebridge/commands/registry.py` — `COMMAND_MODEL_META`

Add:
```python
"gh-create": {"surface": SURFACE_ADVANCED, "namespace": "repo-admin"},
```

### Help text / docs

Update `docs/dispatch-reference.md` to mention `!c gh-create` under the
"Before you dispatch" setup section.

---

## Implementation notes

- `gh repo create --source . --remote origin --push` handles init commit + push
  in one shot, but requires the repo to have at least one commit.
  If the repo is empty (no commits), push will fail. Guard for this: check
  `git log --oneline -1` before pushing; if empty, advise the user to make an
  initial commit first or use `!c start` to let an agent do it.
- Prefer SSH remote when `gh` is configured with SSH keys; `gh repo create`
  picks the right protocol automatically.
- Owner is derived from `gh api user --jq .login`.

---

## Done criteria

- `!c gh-create` on a fresh local repo creates GH repo and wires remote
- `!c gh-create` on a repo that already has a remote reports the URL and exits
- `!c gh-create` on a repo whose GH counterpart exists but has no local remote wires it
- Auth guard: requires gh unlock
- After running, `!c done --pr` succeeds without manual remote setup
- Tests cover the three cases (already wired, exists-on-gh, create-new)
