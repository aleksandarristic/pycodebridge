import pytest

from codebridge.router_helpers import normalize_session, parse_github_clone_url, prune_state_for_repo, rename_state_repo
from codebridge.state import ChannelState, FileState, SessionState


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


def test_prune_state_for_repo_matches_case_insensitive_name():
    fs = FileState()
    fs.channels["chan"] = ChannelState(
        sessions={
            "default": SessionState(
                repo_name="ProbablyFine",
                repo_path="/tmp/ProbablyFine",
                thread_id="thread",
            )
        },
        sticky={"user": "default"},
    )
    prune_state_for_repo(fs, "probablyfine", "/tmp/ProbablyFine")
    assert "chan" not in fs.channels


def test_rename_state_repo_matches_case_insensitive_name():
    fs = FileState()
    fs.channels["chan"] = ChannelState(
        sessions={
            "default": SessionState(
                repo_name="ProbablyFine",
                repo_path="/tmp/ProbablyFine",
                thread_id="thread",
            )
        }
    )
    rename_state_repo(fs, "probablyfine", "/tmp/ProbablyFine", "newrepo", "/tmp/newrepo")
    sess = fs.channels["chan"].sessions["default"]
    assert sess.repo_name == "newrepo"
    assert sess.repo_path == "/tmp/newrepo"
