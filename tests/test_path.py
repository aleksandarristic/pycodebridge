import os

import pytest

from codebridge.util import path as pathutil


def test_resolve_repo_path(tmp_path):
    code_root = tmp_path / "code"
    repo = code_root / "repo"
    gitdir = repo / ".git"
    gitdir.mkdir(parents=True)

    resolved = pathutil.resolve_repo_path(str(code_root), "repo")
    assert resolved == os.path.realpath(str(repo))


def test_resolve_repo_path_invalid_name(tmp_path):
    code_root = tmp_path / "code"
    code_root.mkdir()
    with pytest.raises(ValueError):
        pathutil.resolve_repo_path(str(code_root), "../bad")


def test_resolve_repo_path_for_create(tmp_path):
    code_root = tmp_path / "code"
    code_root.mkdir()
    path = pathutil.resolve_repo_path_for_create(str(code_root), "newrepo")
    assert path.endswith(os.path.join("code", "newrepo"))
