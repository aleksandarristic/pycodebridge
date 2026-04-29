# Docker Run Guide

This project can run inside Docker so Codex subprocesses execute in the container.

Prerequisite: Docker Engine + docker CLI installed and running on the host.

## 1) Prepare Docker config

Copy the example and edit user ids/tokens setup as needed:

```bash
cp config.docker.example.yaml config.docker.yaml
```

Important paths in `config.docker.yaml` are already container-friendly:
- `codex.code_root: /workspace/code_root`
- `state.data_dir: /workspace/state`
- `state.log_dir: /workspace/state/logs`

Default Docker sandbox recommendation:
- Set `codex.sandbox: danger-full-access` in Docker/Compose.
- Reason: Codex `workspace-write` mode may use an inner sandbox (`bwrap`) for tool execution, and that can fail inside containers even when the container itself is privileged and the repo mount is writable.
- Only use `workspace-write` in Docker if your container runtime is known to support that inner sandbox path.

## 2) Prepare host paths

Choose host directories for repos and state (set in shell or in repo `.env`):

```bash
CODE_ROOT_HOST=/absolute/path/to/your/repos
STATE_DIR_HOST=/absolute/path/to/pycodebridge-state
CODEX_AUTH_HOST=/absolute/path/to/codex-auth-dir
GH_CONFIG_HOST=/absolute/path/to/gh-config-dir
HOST_UID=$(id -u)
HOST_GID=$(id -g)
```

`CODE_ROOT_HOST` must contain git repos matched by channel names (`codex-<repo>`).

If `STATE_DIR_HOST` is omitted, `run_docker.sh` defaults it to `./.docker-state`.
If `CODEX_AUTH_HOST` is omitted in Compose, it defaults to `./.docker-codex-auth`.
If `GH_CONFIG_HOST` is omitted in Compose, it defaults to `./.docker-gh-config`.
`HOST_UID/HOST_GID` are required for Compose and should match your host user (`id -u` / `id -g`), otherwise bind mounts can appear read-only inside the container.
To reuse your existing host Codex login with Compose, set `CODEX_AUTH_HOST=$HOME/.codex`.

## 3) Start the container

```bash
./run_docker.sh
```

The script will:
- build image `pycodebridge:local` (unless `BUILD_IMAGE=0`)
- mount repo source at `/app`
- mount `CODE_ROOT_HOST` at `/workspace/code_root`
- mount `STATE_DIR_HOST` at `/workspace/state`
- mount `~/.codex` into container when present for Codex auth reuse
- pass `.env` as `--env-file` when present

Preflight checks only (no build/run):

```bash
./run_docker.sh --check
```

## First-time Codex login in Docker

If Codex returns `401 Missing bearer or basic authentication`, authenticate inside Docker once:

```bash
docker exec -it pycodebridge codex login --device-auth
```

Complete the URL/code flow in your browser, then verify:

```bash
docker exec -it pycodebridge codex login status
```

Auth persistence:
- Both run modes mount Codex auth to `$HOME/.codex` inside container (`HOME=/workspace/home`)
- Compose source is `${CODEX_AUTH_HOST:-./.docker-codex-auth}`
- If Compose auth was not persisted and `run_docker.sh` auth worked, set `CODEX_AUTH_HOST=$HOME/.codex` and restart Compose.
- Both run modes set `XDG_CONFIG_HOME=/workspace/home/.config` and `GH_CONFIG_DIR=/workspace/home/.config/gh`.

## GitHub CLI (`gh`) in Docker

The image includes GitHub CLI. Auth config is persisted at `$HOME/.config/gh` inside container:
- `run_docker.sh`: uses `GH_CONFIG_HOST` if set, else host `~/.config/gh` when available, else `./.docker-gh-config`
- Compose: uses `${GH_CONFIG_HOST:-./.docker-gh-config}`

Authenticate interactively:

```bash
docker exec -it pycodebridge gh auth login
docker exec -it pycodebridge gh auth status
```

Token-based auth (recommended for headless):

```bash
echo "GH_TOKEN=ghp_xxx" >> .env
docker compose up -d --build
```

Note: Codex subprocesses use an environment allowlist. `GH_TOKEN`/`GITHUB_TOKEN` are now forwarded, so setting one in `.env` lets `gh` commands run via Codex sessions use the same token.
`GH_CONFIG_DIR` is also forwarded so Codex-run `gh` commands read the same persisted config path.

Bridge-native command path:
- Use `!c gh <args>` to run GitHub CLI directly via the bridge (without relying on Codex to summarize command output).
- Example: `!c gh repo sync`
- DM example (private repos): `!c gh repo list --visibility private --limit 20`

## Environment knobs

- `IMAGE_NAME` (default `pycodebridge:local`)
- `CONTAINER_NAME` (default `pycodebridge`)
- `CONFIG_IN_REPO` (default `config.docker.yaml`)
- `ENV_IN_REPO` (default `.env`)
- `BUILD_IMAGE` (`1` build before run, `0` skip build)

Example:

```bash
IMAGE_NAME=pycodebridge:dev BUILD_IMAGE=0 ./run_docker.sh
```

## Resetting state quickly

To wipe persisted bridge state/logs:

```bash
./reset_state.sh
```

Behavior:
- If Compose service `codebridge` is running, wipes `/workspace/state` inside that container.
- Otherwise, wipes host state dir from `STATE_DIR_HOST` (or `./.docker-state` fallback).
- You can also pass an explicit host path: `./reset_state.sh /absolute/path/to/state`.

## Notes

- The Docker image installs `codex` via npm (`@openai/codex`).
- The image preinstalls common CLI tools used by Codex/agents: `ripgrep` (`rg`), `fd-find` (`fdfind`), `bat` (`batcat`), `gh`, `jq`, `less`, `procps`, `git`, `curl`.
- Compose runs as `HOST_UID:HOST_GID` and sets `HOME=/workspace/home` to avoid host bind-mount permission mismatches.
- If Discord sessions report `bwrap`/namespace errors while trying to read files, check `config.docker.yaml`: `codex.sandbox` should usually be `danger-full-access` for containerized runs.
- If Codex reports workspace read-only while config says `workspace-write`, run `!c health` and check `Runtime uid:gid` plus `Env sanity` path statuses (`ok(rw)` expected for `code_root`).
- If `~/.codex` is not mounted or not authenticated, exec into the container and run Codex login flow there.
- For local non-Docker runs, use `./run.sh`.

## Headless Compose

`docker-compose.yml` is included for background operation:

```bash
docker compose up -d --build
docker compose logs -f codebridge
docker compose restart codebridge
docker compose down
```

Run device auth inside the Compose service:

```bash
docker compose run --rm --entrypoint codex codebridge login --device-auth
```

## Global skill defaults across repos (TASK-0003)

Use Codex user-level skills for durable defaults that apply across repositories/sessions without editing each repo `AGENTS.md`.

Host-side skill path (when `CODEX_AUTH_HOST` is mounted to `/workspace/home/.codex`):

```text
${CODEX_AUTH_HOST}/skills/<skill-name>/SKILL.md
```

Minimal example:

```bash
mkdir -p "${CODEX_AUTH_HOST}/skills/default-bridge-guidance"
cat > "${CODEX_AUTH_HOST}/skills/default-bridge-guidance/SKILL.md" <<'EOF'
# default-bridge-guidance
- Keep responses concise.
- Run targeted tests only for changed code.
EOF
```

Optional explicit subprocess home in `config.docker.yaml`:

```yaml
codex:
  env:
    CODEX_HOME: "/workspace/home/.codex"
```

Apply steps:

1. Create/update skill files under `${CODEX_AUTH_HOST}/skills/...`.
2. Restart service: `docker compose restart codebridge` (or restart `run_docker.sh` container).
3. Verify in a bridge session that defaults are present.

Precedence/coexistence with repo `AGENTS.md`:

- Use global skill defaults for stable personal/operator conventions across repos.
- Use repo `AGENTS.md` for repository-specific policy and workflow requirements.
- When both exist, keep global defaults generic and repo instructions specific to avoid conflicts.
