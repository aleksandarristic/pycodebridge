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

## 2) Prepare host paths

Choose host directories for repos and state (set in shell or in repo `.env`):

```bash
CODE_ROOT_HOST=/absolute/path/to/your/repos
STATE_DIR_HOST=/absolute/path/to/pycodebridge-state
CODEX_AUTH_HOST=/absolute/path/to/codex-auth-dir
GH_CONFIG_HOST=/absolute/path/to/gh-config-dir
HOST_UID=1000
HOST_GID=1000
```

`CODE_ROOT_HOST` must contain git repos matched by channel names (`codex-<repo>`).

If `STATE_DIR_HOST` is omitted, `run_docker.sh` defaults it to `./.docker-state`.
If `CODEX_AUTH_HOST` is omitted in Compose, it defaults to `./.docker-codex-auth`.
If `GH_CONFIG_HOST` is omitted in Compose, it defaults to `./.docker-gh-config`.
If `HOST_UID/HOST_GID` are omitted, defaults are `1000/1000` for Compose and current shell user for `run_docker.sh`.
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

## Notes

- The Docker image installs `codex` via npm (`@openai/codex`).
- The image preinstalls common CLI tools used by Codex/agents: `ripgrep` (`rg`), `fd-find` (`fdfind`), `bat` (`batcat`), `gh`, `jq`, `less`, `procps`, `git`, `curl`.
- Compose runs as `HOST_UID:HOST_GID` and sets `HOME=/workspace/home` to avoid host bind-mount permission mismatches.
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
