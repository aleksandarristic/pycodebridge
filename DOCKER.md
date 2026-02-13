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

Choose host directories for repos and state:

```bash
export CODE_ROOT_HOST=/absolute/path/to/your/repos
export STATE_DIR_HOST=/absolute/path/to/pycodebridge-state
```

`CODE_ROOT_HOST` must contain git repos matched by channel names (`codex-<repo>`).

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
- If `~/.codex` is not mounted or not authenticated, exec into the container and run Codex login flow there.
- For local non-Docker runs, use `./run.sh`.
