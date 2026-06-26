#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

ENV_IN_REPO="${ENV_IN_REPO:-.env}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_ROOT="$ROOT_DIR/.session-nuke-backups/$TIMESTAMP"

DRY_RUN=1
STOP_COMPOSE=0
RESTART_COMPOSE=0
RESET_BRIDGE=1
RESET_CODEX=1
RESET_CLAUDE=1
RESET_GEMINI=1
DEEP_CLAUDE=0

STATE_DIR_ARG=""
LOG_DIR_ARG=""
CODEX_HOME_ARG=""
CLAUDE_HOME_ARG=""
GEMINI_HOME_ARG=""

usage() {
  cat <<'EOF'
Usage: ./nuke_sessions.sh [options]

Moves bridge/backend session data into .session-nuke-backups/<timestamp> and
recreates empty session directories. It does not remove auth/config files.
Existing pycodebridge sessions and backend conversations will not resume after
this runs unless you manually restore the backup.

By default this is a dry run. Add --yes to perform changes.

Options:
  --yes                 Actually move files/directories.
  --stop-compose        Stop docker compose service "codebridge" before nuking.
  --restart-compose     Start docker compose service "codebridge" afterwards.
  --state-dir DIR       Override pycodebridge state directory.
  --log-dir DIR         Override pycodebridge log directory.
  --codex-home DIR      Override Codex auth/home directory.
  --claude-home DIR     Override Claude config directory.
  --gemini-home DIR     Override Gemini config directory.
  --bridge-only         Reset only pycodebridge state/logs.
  --backends-only       Reset only backend session histories.
  --no-bridge           Do not reset pycodebridge state/logs.
  --no-codex            Do not reset Codex session history.
  --no-claude           Do not reset Claude session history.
  --no-gemini           Do not reset Gemini session history.
  --deep-claude         Move entire Claude projects directory, including memory.
  -h, --help            Show this help.

Typical Docker Compose recovery:
  ./nuke_sessions.sh --yes --stop-compose --restart-compose
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes)
      DRY_RUN=0
      ;;
    --stop-compose)
      STOP_COMPOSE=1
      ;;
    --restart-compose)
      RESTART_COMPOSE=1
      ;;
    --state-dir)
      STATE_DIR_ARG="${2:-}"
      shift
      ;;
    --log-dir)
      LOG_DIR_ARG="${2:-}"
      shift
      ;;
    --codex-home)
      CODEX_HOME_ARG="${2:-}"
      shift
      ;;
    --claude-home)
      CLAUDE_HOME_ARG="${2:-}"
      shift
      ;;
    --gemini-home)
      GEMINI_HOME_ARG="${2:-}"
      shift
      ;;
    --bridge-only)
      RESET_BRIDGE=1
      RESET_CODEX=0
      RESET_CLAUDE=0
      RESET_GEMINI=0
      ;;
    --backends-only)
      RESET_BRIDGE=0
      RESET_CODEX=1
      RESET_CLAUDE=1
      RESET_GEMINI=1
      ;;
    --no-bridge)
      RESET_BRIDGE=0
      ;;
    --no-codex)
      RESET_CODEX=0
      ;;
    --no-claude)
      RESET_CLAUDE=0
      ;;
    --no-gemini)
      RESET_GEMINI=0
      ;;
    --deep-claude)
      DEEP_CLAUDE=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

load_env_file() {
  if [[ -f "$ROOT_DIR/$ENV_IN_REPO" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ROOT_DIR/$ENV_IN_REPO"
    set +a
  fi
}

config_value() {
  local file="$1"
  local section="$2"
  local key="$3"

  [[ -f "$file" ]] || return 1
  awk -v section="$section" -v key="$key" '
    /^[[:space:]]*#/ { next }
    /^[A-Za-z_][A-Za-z0-9_-]*:[[:space:]]*$/ {
      current=$1
      sub(/:$/, "", current)
      next
    }
    current == section && $1 == key ":" {
      value=$0
      sub("^[[:space:]]*" key ":[[:space:]]*", "", value)
      sub(/[[:space:]]+#.*/, "", value)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      gsub(/^"/, "", value)
      gsub(/"$/, "", value)
      gsub(/^'\''/, "", value)
      gsub(/'\''$/, "", value)
      print value
      exit
    }
  ' "$file"
}

abs_path() {
  local path="$1"
  [[ -n "$path" ]] || return 1
  if [[ "$path" == "~" ]]; then
    path="$HOME"
  elif [[ "$path" == "~/"* ]]; then
    path="$HOME/${path#"~/"}"
  fi
  if [[ "$path" == /* ]]; then
    printf '%s\n' "$path"
  else
    printf '%s\n' "$ROOT_DIR/$path"
  fi
}

path_exists() {
  [[ -e "$1" || -L "$1" ]]
}

print_cmd() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
}

run_cmd() {
  print_cmd "$@"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    "$@"
  fi
}

ensure_backup_root() {
  if [[ "$DRY_RUN" -eq 0 ]]; then
    mkdir -p "$BACKUP_ROOT"
  fi
}

backup_dest_for() {
  local src="$1"
  local category="$2"
  local base="${3:-}"
  local rel

  if [[ -n "$base" && "$src" == "$base/"* ]]; then
    rel="${src#"$base/"}"
  else
    rel="$(basename "$src")"
  fi
  printf '%s/%s/%s\n' "$BACKUP_ROOT" "$category" "$rel"
}

move_to_backup() {
  local src="$1"
  local category="$2"
  local base="${3:-}"
  local dest

  if ! path_exists "$src"; then
    echo "skip missing: $src"
    return 0
  fi

  dest="$(backup_dest_for "$src" "$category" "$base")"
  ensure_backup_root
  run_cmd mkdir -p "$(dirname "$dest")"
  run_cmd mv "$src" "$dest"
}

recreate_dir() {
  local dir="$1"
  [[ -n "$dir" ]] || return 0
  run_cmd mkdir -p "$dir"
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

resolve_state_dir() {
  local from_config

  if [[ -n "$STATE_DIR_ARG" ]]; then
    abs_path "$STATE_DIR_ARG"
    return 0
  fi
  if [[ -n "${STATE_DIR_HOST:-}" ]]; then
    abs_path "$STATE_DIR_HOST"
    return 0
  fi
  if [[ -d "$ROOT_DIR/.docker-state" ]]; then
    abs_path "$ROOT_DIR/.docker-state"
    return 0
  fi
  from_config="$(config_value "$ROOT_DIR/config.yaml" state data_dir || true)"
  if [[ -n "$from_config" && "$from_config" != /workspace/* ]]; then
    abs_path "$from_config"
    return 0
  fi
  return 1
}

resolve_log_dir() {
  local state_dir="$1"
  local from_config

  if [[ -n "$LOG_DIR_ARG" ]]; then
    abs_path "$LOG_DIR_ARG"
    return 0
  fi
  if [[ -n "${STATE_DIR_ARG:-}" || -n "${STATE_DIR_HOST:-}" ]]; then
    if [[ -n "$state_dir" ]]; then
      printf '%s\n' "$state_dir/logs"
      return 0
    fi
  fi
  if [[ -d "$ROOT_DIR/.docker-state" ]]; then
    if [[ -n "$state_dir" ]]; then
      printf '%s\n' "$state_dir/logs"
      return 0
    fi
  fi
  from_config="$(config_value "$ROOT_DIR/config.yaml" state log_dir || true)"
  if [[ -n "$from_config" && "$from_config" != /workspace/* ]]; then
    abs_path "$from_config"
    return 0
  fi
  if [[ -n "$state_dir" ]]; then
    printf '%s\n' "$state_dir/logs"
    return 0
  fi
  return 1
}

resolve_codex_home() {
  if [[ -n "$CODEX_HOME_ARG" ]]; then
    abs_path "$CODEX_HOME_ARG"
  elif [[ -n "${CODEX_AUTH_HOST:-}" ]]; then
    abs_path "$CODEX_AUTH_HOST"
  elif [[ -d "$ROOT_DIR/.docker-codex-auth" ]]; then
    abs_path "$ROOT_DIR/.docker-codex-auth"
  elif [[ -n "${CODEX_HOME:-}" ]]; then
    abs_path "$CODEX_HOME"
  else
    abs_path "$HOME/.codex"
  fi
}

resolve_claude_home() {
  if [[ -n "$CLAUDE_HOME_ARG" ]]; then
    abs_path "$CLAUDE_HOME_ARG"
  elif [[ -n "${CLAUDE_AUTH_HOST:-}" ]]; then
    abs_path "$CLAUDE_AUTH_HOST"
  elif [[ -d "$ROOT_DIR/.docker-claude-auth" ]]; then
    abs_path "$ROOT_DIR/.docker-claude-auth"
  elif [[ -n "${CLAUDE_CONFIG_DIR:-}" ]]; then
    abs_path "$CLAUDE_CONFIG_DIR"
  else
    abs_path "$HOME/.claude"
  fi
}

resolve_gemini_home() {
  if [[ -n "$GEMINI_HOME_ARG" ]]; then
    abs_path "$GEMINI_HOME_ARG"
  elif [[ -n "${GEMINI_AUTH_HOST:-}" ]]; then
    abs_path "$GEMINI_AUTH_HOST"
  elif [[ -d "$ROOT_DIR/.docker-gemini-auth" ]]; then
    abs_path "$ROOT_DIR/.docker-gemini-auth"
  else
    abs_path "$HOME/.gemini"
  fi
}

reset_bridge_state() {
  local state_dir="$1"
  local log_dir="$2"

  if [[ -z "$state_dir" ]]; then
    echo "skip bridge: state directory could not be resolved"
    return 0
  fi

  echo "Bridge state: $state_dir"
  move_to_backup "$state_dir" bridge ""
  recreate_dir "$state_dir"

  if [[ -n "$log_dir" && "$log_dir" != "$state_dir" && "$log_dir" != "$state_dir/"* ]]; then
    echo "Bridge logs: $log_dir"
    move_to_backup "$log_dir" bridge ""
    recreate_dir "$log_dir"
  fi
}

reset_codex_sessions() {
  local home_dir="$1"

  echo "Codex home: $home_dir"
  move_to_backup "$home_dir/sessions" codex "$home_dir"
  recreate_dir "$home_dir/sessions"
}

reset_claude_sessions() {
  local home_dir="$1"

  echo "Claude home: $home_dir"
  if [[ "$DEEP_CLAUDE" -eq 1 ]]; then
    move_to_backup "$home_dir/projects" claude "$home_dir"
    recreate_dir "$home_dir/projects"
  else
    if [[ -d "$home_dir/projects" ]]; then
      while IFS= read -r -d '' path; do
        move_to_backup "$path" claude "$home_dir"
      done < <(find "$home_dir/projects" -type f \( -name '*.jsonl' -o -name 'sessions-index.json' \) -print0)
    else
      echo "skip missing: $home_dir/projects"
    fi
  fi

  move_to_backup "$home_dir/sessions" claude "$home_dir"
  move_to_backup "$home_dir/session-env" claude "$home_dir"
  move_to_backup "$home_dir/file-history" claude "$home_dir"
  move_to_backup "$home_dir/tasks" claude "$home_dir"
  move_to_backup "$home_dir/history.jsonl" claude "$home_dir"
  recreate_dir "$home_dir/projects"
  recreate_dir "$home_dir/sessions"
}

reset_gemini_sessions() {
  local home_dir="$1"

  echo "Gemini home: $home_dir"
  move_to_backup "$home_dir/sessions" gemini "$home_dir"
  move_to_backup "$home_dir/tmp" gemini "$home_dir"
  move_to_backup "$home_dir/history.jsonl" gemini "$home_dir"
  recreate_dir "$home_dir/sessions"
}

print_warning() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    cat <<EOF
DRY RUN: add --yes to perform changes.

WARNING:
  This script is for emergency recovery from poisoned/stale sessions.
  It will move active session state out of the paths below, so existing
  pycodebridge, Codex, Claude, and Gemini conversations will stop resuming.
  Auth/config files are intentionally left in place.

EOF
  else
    cat <<EOF
WARNING: SESSION NUKE IS ARMED.
  Existing pycodebridge and backend conversations will stop resuming.
  Session data will be moved into a backup directory, not deleted.
  Auth/config files are intentionally left in place.

EOF
  fi
}

load_env_file

STATE_DIR="$(resolve_state_dir || true)"
LOG_DIR="$(resolve_log_dir "$STATE_DIR" || true)"
CODEX_HOME_RESOLVED="$(resolve_codex_home)"
CLAUDE_HOME_RESOLVED="$(resolve_claude_home)"
GEMINI_HOME_RESOLVED="$(resolve_gemini_home)"

print_warning
echo "Backup root: $BACKUP_ROOT"

if compose_service_running; then
  if [[ "$STOP_COMPOSE" -eq 1 ]]; then
    run_cmd docker compose stop codebridge
  else
    echo "codebridge compose service appears to be running."
    echo "Stop it first or rerun with --stop-compose."
    if [[ "$DRY_RUN" -eq 0 ]]; then
      exit 1
    fi
  fi
fi

if [[ "$RESET_BRIDGE" -eq 1 ]]; then
  reset_bridge_state "$STATE_DIR" "$LOG_DIR"
fi
if [[ "$RESET_CODEX" -eq 1 ]]; then
  reset_codex_sessions "$CODEX_HOME_RESOLVED"
fi
if [[ "$RESET_CLAUDE" -eq 1 ]]; then
  reset_claude_sessions "$CLAUDE_HOME_RESOLVED"
fi
if [[ "$RESET_GEMINI" -eq 1 ]]; then
  reset_gemini_sessions "$GEMINI_HOME_RESOLVED"
fi

if [[ "$RESTART_COMPOSE" -eq 1 ]]; then
  run_cmd docker compose up -d codebridge
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "Dry run complete."
else
  echo "Session data moved to: $BACKUP_ROOT"
  echo "Session nuke complete."
fi
