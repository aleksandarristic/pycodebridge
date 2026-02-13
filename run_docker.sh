#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="${IMAGE_NAME:-pycodebridge:local}"
CONTAINER_NAME="${CONTAINER_NAME:-pycodebridge}"
CONFIG_IN_REPO="${CONFIG_IN_REPO:-config.docker.yaml}"
ENV_IN_REPO="${ENV_IN_REPO:-.env}"
CODE_ROOT_HOST="${CODE_ROOT_HOST:-}"
STATE_DIR_HOST="${STATE_DIR_HOST:-$ROOT_DIR/.docker-state}"
GH_CONFIG_HOST="${GH_CONFIG_HOST:-}"
CODEX_AUTH_HOST="${CODEX_AUTH_HOST:-}"
HOST_UID="${HOST_UID:-$(id -u)}"
HOST_GID="${HOST_GID:-$(id -g)}"
BUILD_IMAGE="${BUILD_IMAGE:-1}"
MODE="run"

if [[ "${1:-}" == "--check" ]]; then
  MODE="check"
  shift
fi

# Allow CODE_ROOT_HOST / STATE_DIR_HOST to come from repo .env without
# requiring export in the shell every run.
if [[ -f "$ROOT_DIR/$ENV_IN_REPO" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/$ENV_IN_REPO"
  set +a
  CODE_ROOT_HOST="${CODE_ROOT_HOST:-}"
  STATE_DIR_HOST="${STATE_DIR_HOST:-$ROOT_DIR/.docker-state}"
  GH_CONFIG_HOST="${GH_CONFIG_HOST:-}"
  CODEX_AUTH_HOST="${CODEX_AUTH_HOST:-}"
  HOST_UID="${HOST_UID:-$(id -u)}"
  HOST_GID="${HOST_GID:-$(id -g)}"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker command not found." >&2
  exit 1
fi

if [[ -z "$CODE_ROOT_HOST" ]]; then
  echo "Error: CODE_ROOT_HOST is required (host path for repos mapped to /workspace/code_root)." >&2
  echo "Set it in shell or .env, for example:" >&2
  echo "  CODE_ROOT_HOST=\$HOME/Code STATE_DIR_HOST=\$HOME/.pycodebridge-docker ./run_docker.sh" >&2
  exit 1
fi
if [[ -z "$STATE_DIR_HOST" ]]; then
  echo "Error: STATE_DIR_HOST is required (host path for bridge state/logs mapped to /workspace/state)." >&2
  exit 1
fi

if [[ ! -d "$CODE_ROOT_HOST" ]]; then
  echo "Error: CODE_ROOT_HOST is not a directory: $CODE_ROOT_HOST" >&2
  exit 1
fi

CODE_ROOT_HOST="$(cd "$CODE_ROOT_HOST" && pwd)"
mkdir -p "$STATE_DIR_HOST"
STATE_DIR_HOST="$(cd "$STATE_DIR_HOST" && pwd)"

if [[ -z "$GH_CONFIG_HOST" ]]; then
  if [[ -d "$HOME/.config/gh" ]]; then
    GH_CONFIG_HOST="$HOME/.config/gh"
  else
    GH_CONFIG_HOST="$ROOT_DIR/.docker-gh-config"
  fi
fi
mkdir -p "$GH_CONFIG_HOST"
GH_CONFIG_HOST="$(cd "$GH_CONFIG_HOST" && pwd)"

if [[ -z "$CODEX_AUTH_HOST" ]]; then
  if [[ -d "$HOME/.codex" ]]; then
    CODEX_AUTH_HOST="$HOME/.codex"
  else
    CODEX_AUTH_HOST="$ROOT_DIR/.docker-codex-auth"
  fi
fi
mkdir -p "$CODEX_AUTH_HOST"
CODEX_AUTH_HOST="$(cd "$CODEX_AUTH_HOST" && pwd)"

if [[ ! -f "$ROOT_DIR/$CONFIG_IN_REPO" ]]; then
  echo "Error: config file not found in repo: $CONFIG_IN_REPO" >&2
  echo "Tip: copy config.docker.example.yaml to config.docker.yaml and edit it." >&2
  exit 1
fi

if [[ "$BUILD_IMAGE" == "1" ]]; then
  docker build -t "$IMAGE_NAME" "$ROOT_DIR"
fi

docker_args=(
  run --rm -it
  --name "$CONTAINER_NAME"
  -u "$HOST_UID:$HOST_GID"
  -e HOME=/workspace/home
  -e XDG_CONFIG_HOME=/workspace/home/.config
  -e GH_CONFIG_DIR=/workspace/home/.config/gh
  -v "$ROOT_DIR:/app"
  -v "$CODE_ROOT_HOST:/workspace/code_root"
  -v "$STATE_DIR_HOST:/workspace/state"
  -v "$CODEX_AUTH_HOST:/workspace/home/.codex"
  -v "$GH_CONFIG_HOST:/workspace/home/.config/gh"
)

if [[ -f "$ROOT_DIR/$ENV_IN_REPO" ]]; then
  docker_args+=( --env-file "$ROOT_DIR/$ENV_IN_REPO" )
else
  echo "Warning: env file not found: $ENV_IN_REPO (continuing without --env-file)." >&2
fi

if [[ "$MODE" == "check" ]]; then
  echo "OK: docker available"
  echo "OK: code root mount source: $CODE_ROOT_HOST"
  echo "OK: state mount source: $STATE_DIR_HOST"
  echo "OK: container runtime uid:gid = $HOST_UID:$HOST_GID"
  echo "OK: Codex auth mount source: $CODEX_AUTH_HOST"
  echo "OK: GitHub CLI config mount source: $GH_CONFIG_HOST"
  echo "OK: config file in repo: $ROOT_DIR/$CONFIG_IN_REPO"
  if [[ -f "$ROOT_DIR/$ENV_IN_REPO" ]]; then
    echo "OK: env file in repo: $ROOT_DIR/$ENV_IN_REPO"
  else
    echo "WARN: env file missing in repo: $ROOT_DIR/$ENV_IN_REPO"
  fi
  echo "OK: dry-run checks completed"
  exit 0
fi

exec docker "${docker_args[@]}" "$IMAGE_NAME" -config "/app/$CONFIG_IN_REPO"
