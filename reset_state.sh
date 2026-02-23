#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

STATE_DIR_ARG="${1:-}"
ENV_IN_REPO="${ENV_IN_REPO:-.env}"

load_env_file() {
  if [[ -f "$ROOT_DIR/$ENV_IN_REPO" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ROOT_DIR/$ENV_IN_REPO"
    set +a
  fi
}

compose_service_running() {
  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    return 1
  fi
  local cid
  cid="$(docker compose ps -q codebridge 2>/dev/null || true)"
  [[ -n "$cid" ]]
}

wipe_dir_contents() {
  local dir="$1"
  mkdir -p "$dir"
  rm -rf "${dir}/"* "${dir}"/.[!.]* "${dir}"/..?* 2>/dev/null || true
}

reset_container_state() {
  echo "Resetting state inside running docker compose service 'codebridge'..."
  docker compose exec -T codebridge sh -lc 'mkdir -p /workspace/state && rm -rf /workspace/state/* /workspace/state/.[!.]* /workspace/state/..?* 2>/dev/null || true'
  echo "Container state reset complete: /workspace/state"
}

resolve_host_state_dir() {
  if [[ -n "$STATE_DIR_ARG" ]]; then
    echo "$STATE_DIR_ARG"
    return 0
  fi
  if [[ -n "${STATE_DIR_HOST:-}" ]]; then
    echo "$STATE_DIR_HOST"
    return 0
  fi
  if [[ -d "$ROOT_DIR/.docker-state" ]]; then
    echo "$ROOT_DIR/.docker-state"
    return 0
  fi
  return 1
}

load_env_file

if compose_service_running; then
  reset_container_state
  echo "Tip: restart the service if you want a fully clean runtime: docker compose restart codebridge"
  exit 0
fi

host_state_dir="$(resolve_host_state_dir || true)"
if [[ -z "$host_state_dir" ]]; then
  echo "Error: unable to resolve state directory." >&2
  echo "Provide an explicit path: ./reset_state.sh /absolute/path/to/state" >&2
  echo "Or set STATE_DIR_HOST in .env." >&2
  exit 1
fi

echo "Resetting host state directory: $host_state_dir"
wipe_dir_contents "$host_state_dir"
echo "Host state reset complete."
