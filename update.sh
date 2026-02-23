#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./update.sh [branch]
  ./update.sh --check
  ./update.sh -h|--help

Behavior:
  - Fetches latest refs from origin
  - Optionally checks out the provided branch
  - Pulls latest code with --ff-only
  - Stops docker compose stack
  - Rebuilds and starts docker compose stack

--check:
  Runs preflight checks only; makes no changes.
EOF
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

CHECK_ONLY=0
BRANCH=""

case "${1:-}" in
  "")
    ;;
  --check)
    CHECK_ONLY=1
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    BRANCH="$1"
    ;;
esac

need_cmd git
need_cmd docker

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is required (docker compose ...)." >&2
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a git repository: $ROOT_DIR" >&2
  exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "Git remote 'origin' is not configured." >&2
  exit 1
fi

echo "==> Repo: $ROOT_DIR"
echo "==> Branch: $(git rev-parse --abbrev-ref HEAD)"
echo "==> Head: $(git rev-parse --short HEAD)"

if [ -n "$(git status --porcelain)" ]; then
  echo "==> Working tree has local changes."
else
  echo "==> Working tree is clean."
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "==> Running preflight checks..."
  git fetch --prune origin
  docker compose config -q
  echo "==> Preflight passed. No changes were made."
  exit 0
fi

echo "==> Fetching latest refs"
git fetch --prune origin

if [ -n "$BRANCH" ]; then
  echo "==> Checking out branch: $BRANCH"
  git checkout "$BRANCH"
fi

echo "==> Pulling latest code (ff-only)"
git pull --ff-only

echo "==> Stopping docker compose stack"
docker compose down

echo "==> Rebuilding and starting docker compose stack"
docker compose up -d --build

echo "==> Update complete"
echo "==> New head: $(git rev-parse --short HEAD)"
docker compose ps
