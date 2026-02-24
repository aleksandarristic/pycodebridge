#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./update.sh [branch]
  ./update.sh --check
  ./update.sh --dry-run [branch]
  ./update.sh -h|--help

Behavior:
  - Fetches latest refs from origin
  - Optionally checks out the provided branch
  - Pulls latest code with --ff-only
  - Stops docker compose stack
  - Rebuilds and starts docker compose stack
  - Verifies (warn-only) Codex CLI + GitHub CLI auth inside running container

--check:
  Runs preflight checks only; makes no changes.

--dry-run:
  Shows planned update actions; makes no changes.
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
DRY_RUN=0
BRANCH=""

while [ $# -gt 0 ]; do
  case "$1" in
    --check)
      CHECK_ONLY=1
      ;;
    --dry-run|-n)
      DRY_RUN=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Unknown flag: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      if [ -n "$BRANCH" ]; then
        echo "Only one branch argument is allowed." >&2
        usage >&2
        exit 1
      fi
      BRANCH="$1"
      ;;
  esac
  shift
done

if [ "$CHECK_ONLY" -eq 1 ] && [ "$DRY_RUN" -eq 1 ]; then
  echo "Use only one mode: --check or --dry-run." >&2
  exit 1
fi

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

if [ "$DRY_RUN" -eq 1 ]; then
  echo "==> Dry-run mode (no changes will be made)"
  docker compose config -q
  echo "Would run: git fetch --prune origin"
  if [ -n "$BRANCH" ]; then
    echo "Would run: git checkout $BRANCH"
  fi
  echo "Would run: git pull --ff-only"
  echo "Would run: docker compose down"
  echo "Would run: docker compose up -d --build"
  echo "Would run: auth checks inside service 'codebridge' (warn-only)"
  echo "Dry-run complete."
  exit 0
fi

check_container_auth() {
  echo "==> Checking in-container auth status (warn-only)"
  if ! docker compose ps --status running --services 2>/dev/null | grep -qx "codebridge"; then
    echo "WARN: Service 'codebridge' is not running; skipped auth checks."
    echo "      Start it with: docker compose up -d --build"
    return 0
  fi

  if codex_status="$(docker compose exec -T codebridge codex login status 2>&1)"; then
    echo "OK: Codex CLI authentication is available in the container."
  else
    echo "WARN: Codex CLI is not authenticated in the container."
    echo "      To fix: docker compose run --rm --entrypoint codex codebridge login --device-auth"
    echo "      Status output: $(printf '%s' "$codex_status" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g')"
  fi

  if gh_status="$(docker compose exec -T codebridge gh auth status -h github.com 2>&1)"; then
    echo "OK: GitHub CLI authentication is available in the container."
  else
    echo "WARN: GitHub CLI is not authenticated in the container."
    echo "      To fix: docker compose exec -T codebridge gh auth login -h github.com --web"
    echo "      Status output: $(printf '%s' "$gh_status" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g')"
  fi
}

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

check_container_auth

echo "==> Update complete"
echo "==> New head: $(git rev-parse --short HEAD)"
docker compose ps
