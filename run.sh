#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
VENV_ACTIVATE="$VENV_DIR/bin/activate"
MODE="run"
if [[ "${1:-}" == "--check" ]]; then
  MODE="check"
  shift
fi
CONFIG_PATH="${1:-$ROOT_DIR/config.yaml}"
ENV_PATH="${2:-}"

if [[ ! -f "$VENV_ACTIVATE" ]]; then
  echo "Error: missing virtualenv at $VENV_DIR" >&2
  echo "Create it first, for example:" >&2
  echo "  python3 -m venv .venv" >&2
  echo "  ./.venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "Error: config file not found: $CONFIG_PATH" >&2
  exit 1
fi

if [[ "${VIRTUAL_ENV:-}" != "$VENV_DIR" ]]; then
  # shellcheck disable=SC1090
  source "$VENV_ACTIVATE"
fi

if [[ -n "$ENV_PATH" && ! -f "$ENV_PATH" ]]; then
  echo "Error: env file not found: $ENV_PATH" >&2
  exit 1
fi

if ! command -v codex >/dev/null 2>&1; then
  echo "Warning: 'codex' binary is not on PATH. Set codex.binary in config if needed." >&2
fi

if [[ "$MODE" == "check" ]]; then
  echo "OK: venv found at $VENV_DIR"
  echo "OK: config found at $CONFIG_PATH"
  if [[ -n "$ENV_PATH" ]]; then
    echo "OK: env file found at $ENV_PATH"
  fi
  if command -v codex >/dev/null 2>&1; then
    echo "OK: codex binary available: $(command -v codex)"
  else
    echo "WARN: codex binary not on PATH (set codex.binary in config if needed)"
  fi
  exit 0
fi

cmd=(python -m cmd.bridge -config "$CONFIG_PATH")
if [[ -n "$ENV_PATH" ]]; then
  cmd+=( -env "$ENV_PATH" )
fi

exec "${cmd[@]}"
