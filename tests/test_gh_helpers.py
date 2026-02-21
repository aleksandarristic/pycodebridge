from codebridge.handlers.gh_helpers import _gh_clone_completion_hint


def test_gh_clone_completion_hint_for_repo_clone_with_slug():
    msg = _gh_clone_completion_hint(["repo", "clone", "owner/MyRepo"])
    assert msg == "Clone complete. Use `#codex-myrepo` for prompts."


def test_gh_clone_completion_hint_for_repo_clone_with_target_dir():
    msg = _gh_clone_completion_hint(["repo", "clone", "owner/repo", "LocalRepo"])
    assert msg == "Clone complete. Use `#codex-localrepo` for prompts."


def test_gh_clone_completion_hint_for_non_clone_command():
    assert _gh_clone_completion_hint(["pr", "status"]) == ""
