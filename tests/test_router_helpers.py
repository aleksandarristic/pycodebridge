import pytest

from codebridge.router import normalize_session, parse_github_clone_url


def test_normalize_session():
    assert normalize_session("") == "default"
    assert normalize_session("abc") == "abc"
    with pytest.raises(ValueError):
        normalize_session("bad name")


def test_parse_github_clone_url():
    assert parse_github_clone_url("github.com/owner/repo") == "https://github.com/owner/repo.git"
    assert parse_github_clone_url("git@github.com:owner/repo.git") == "https://github.com/owner/repo.git"
    with pytest.raises(ValueError):
        parse_github_clone_url("https://example.com/owner/repo")
