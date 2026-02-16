"""Path containment helpers for repo resolution."""

import os
import re

_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def normalize_repo_name(repo_name: str) -> str:
    """Return the canonical repo identifier used by channels and state."""
    _validate_repo_name(repo_name)
    return repo_name.lower()


def resolve_repo_path(code_root: str, repo_name: str) -> str:
    """Resolve and validate a repo path under code_root."""
    repo_key = normalize_repo_name(repo_name)
    code_root_abs = _abs_clean(code_root)
    code_root_real = _realpath_or_self(code_root_abs)

    repo_abs = os.path.abspath(os.path.join(code_root_real, repo_key))
    repo_real = _realpath_or_self(repo_abs)

    _ensure_contained(code_root_real, repo_real)

    if not os.path.isdir(repo_real):
        repo_real = _resolve_case_variant_repo_path(code_root_real, repo_key)

    if not os.path.isdir(repo_real):
        raise ValueError("repo path is not a directory")
    if not os.path.isdir(os.path.join(repo_real, ".git")):
        raise ValueError("repo is not a git repository (.git missing)")

    return repo_real


def resolve_repo_path_for_create(code_root: str, repo_name: str) -> str:
    """Resolve a repo path for creation under code_root."""
    repo_key = normalize_repo_name(repo_name)
    code_root_abs = _abs_clean(code_root)
    code_root_real = _realpath_or_self(code_root_abs)

    repo_abs = os.path.abspath(os.path.join(code_root_real, repo_key))
    _ensure_contained(code_root_real, repo_abs)

    case_variants = _find_case_variant_repo_paths(code_root_real, repo_key)
    if case_variants and repo_abs not in case_variants:
        raise ValueError("repo path already exists with different case")

    if os.path.exists(repo_abs) and not os.path.isdir(repo_abs):
        raise ValueError("repo path exists and is not a directory")
    return repo_abs


def _validate_repo_name(repo_name: str) -> None:
    """Validate repo names against allowed characters and separators."""
    if not repo_name or not _REPO_NAME_RE.match(repo_name):
        raise ValueError(f"invalid repo name {repo_name!r}")
    if any(c in repo_name for c in ("/", "\\", ":")) or repo_name == "..":
        raise ValueError(f"invalid repo name {repo_name!r}")


def _abs_clean(path: str) -> str:
    """Return an absolute, normalized path."""
    if not path:
        raise ValueError("code_root is required")
    return os.path.abspath(os.path.normpath(path))


def _realpath_or_self(path: str) -> str:
    """Return realpath or the original path on failure."""
    try:
        return os.path.realpath(path)
    except OSError:
        return path


def _ensure_contained(root: str, child: str) -> None:
    """Ensure child path is contained within root."""
    rel = os.path.relpath(child, root)
    if rel == ".":
        raise ValueError("repo cannot be the code root")
    if rel.startswith(".."):
        raise ValueError("repo escapes code root")


def resolve_repo_file_path(repo_path: str, rel_path: str) -> str:
    """Resolve and validate a file path under a repo directory."""
    if not rel_path:
        raise ValueError("path is required")
    if os.path.isabs(rel_path):
        raise ValueError("path must be relative")
    cleaned = rel_path.lstrip("/").lstrip("\\")
    target = os.path.abspath(os.path.join(repo_path, cleaned))
    _ensure_contained(_realpath_or_self(repo_path), _realpath_or_self(target))
    return target


def _resolve_case_variant_repo_path(code_root: str, repo_key: str) -> str:
    """Return a repo path that matches repo_key ignoring case, if unique."""
    matches = _find_case_variant_repo_paths(code_root, repo_key)
    if len(matches) > 1:
        raise ValueError("multiple repo directories match name with different case")
    if not matches:
        return os.path.abspath(os.path.join(code_root, repo_key))
    return matches[0]


def _find_case_variant_repo_paths(code_root: str, repo_key: str) -> list[str]:
    """Find case-variant repo paths matching repo_key under code_root."""
    try:
        entries = os.listdir(code_root)
    except OSError:
        return []
    matches: list[str] = []
    for entry in entries:
        if entry.lower() != repo_key:
            continue
        candidate_abs = os.path.abspath(os.path.join(code_root, entry))
        candidate_real = _realpath_or_self(candidate_abs)
        try:
            _ensure_contained(code_root, candidate_real)
        except ValueError:
            continue
        matches.append(candidate_abs)
    return matches
