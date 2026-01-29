import os
import re

_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def resolve_repo_path(code_root: str, repo_name: str) -> str:
    _validate_repo_name(repo_name)
    code_root_abs = _abs_clean(code_root)
    code_root_real = _realpath_or_self(code_root_abs)

    repo_abs = os.path.abspath(os.path.join(code_root_real, repo_name))
    repo_real = _realpath_or_self(repo_abs)

    _ensure_contained(code_root_real, repo_real)

    if not os.path.isdir(repo_real):
        raise ValueError("repo path is not a directory")
    if not os.path.isdir(os.path.join(repo_real, ".git")):
        raise ValueError("repo is not a git repository (.git missing)")

    return repo_real


def resolve_repo_path_for_create(code_root: str, repo_name: str) -> str:
    _validate_repo_name(repo_name)
    code_root_abs = _abs_clean(code_root)
    code_root_real = _realpath_or_self(code_root_abs)

    repo_abs = os.path.abspath(os.path.join(code_root_real, repo_name))
    _ensure_contained(code_root_real, repo_abs)

    if os.path.exists(repo_abs) and not os.path.isdir(repo_abs):
        raise ValueError("repo path exists and is not a directory")
    return repo_abs


def _validate_repo_name(repo_name: str) -> None:
    if not repo_name or not _REPO_NAME_RE.match(repo_name):
        raise ValueError(f"invalid repo name {repo_name!r}")
    if any(c in repo_name for c in ("/", "\\", ":")) or repo_name == "..":
        raise ValueError(f"invalid repo name {repo_name!r}")


def _abs_clean(path: str) -> str:
    if not path:
        raise ValueError("code_root is required")
    return os.path.abspath(os.path.normpath(path))


def _realpath_or_self(path: str) -> str:
    try:
        return os.path.realpath(path)
    except OSError:
        return path


def _ensure_contained(root: str, child: str) -> None:
    rel = os.path.relpath(child, root)
    if rel == ".":
        raise ValueError("repo cannot be the code root")
    if rel.startswith(".."):
        raise ValueError("repo escapes code root")

