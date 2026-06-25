"""GitHub CLI helper command handlers."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from ..routing.helpers import run_limited_command, trim_output
from ..platform.transport import ResponseSink
from ..util.ansi import strip_control_codes
from ..util import path as pathutil

if TYPE_CHECKING:
    from ..routing.router import Router


async def handle_gh(router: "Router", sink: ResponseSink, repo_path: str, rest: str) -> None:
    """Run gh helper commands directly in the repo directory."""
    fields = shlex.split(rest) if rest else []
    if not fields:
        await router.reply(sink, "Usage: !c gh <args> (example: !c gh repo sync)")
        return

    out, err = await run_limited_command(repo_path, ["gh"] + fields)
    text = strip_control_codes(out)
    text = trim_output(text, 300, 6000)
    if err:
        text = f"gh error: {err}\n{text}"
    elif not text.strip():
        text = "gh command completed successfully (no output)."
    else:
        text = text.strip()
    await router.reply(sink, text)
    if not err:
        completion = _gh_clone_completion_hint(fields)
        if completion:
            await router.reply(sink, completion)


async def handle_gh_create(router: "Router", sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    """Create or wire a GitHub repo for the current local repo."""
    try:
        fields = shlex.split(rest) if rest else []
    except ValueError as exc:
        await router.reply_forbidden(sink, f"Usage: !c gh-create [--public]\nInvalid args: {exc}")
        return
    if any(field != "--public" for field in fields):
        await router.reply_forbidden(sink, "Usage: !c gh-create [--public]")
        return
    visibility = "--public" if "--public" in fields else "--private"

    if not await _ensure_git_repo(router, sink, repo_path):
        return

    remote_out, remote_err = await run_limited_command(repo_path, ["git", "remote", "get-url", "origin"])
    remote_url = _clean_output(remote_out)
    if remote_err is None and remote_url:
        await router.reply(sink, f"Remote already configured: {remote_url}")
        return

    owner = await _gh_owner(router, sink, repo_path)
    if not owner:
        return
    full_name = f"{owner}/{repo_name}"

    view_out, view_err = await run_limited_command(
        repo_path,
        [
            "gh",
            "repo",
            "view",
            full_name,
            "--json",
            "sshUrl,url",
            "--jq",
            "if (.sshUrl // \"\") != \"\" then .sshUrl else .url end",
        ],
    )
    if view_err is None:
        existing_url = _clean_output(view_out)
        if not existing_url:
            await router.reply(sink, f"Could not determine remote URL for existing GitHub repo {full_name}.")
            return
        add_out, add_err = await run_limited_command(repo_path, ["git", "remote", "add", "origin", existing_url])
        if add_err:
            await router.reply(sink, f"git remote add failed: {_format_command_failure(add_out, add_err)}")
            return
        fetch_out, fetch_err = await run_limited_command(repo_path, ["git", "fetch", "origin"])
        if fetch_err:
            await router.reply(sink, f"git fetch origin failed: {_format_command_failure(fetch_out, fetch_err)}")
            return
        await router.reply(sink, f"Remote wired to existing GitHub repo: {existing_url}")
        return

    log_out, log_err = await run_limited_command(repo_path, ["git", "log", "--oneline", "-1"])
    if log_err or not _clean_output(log_out):
        await router.reply(
            sink,
            "GitHub repo was not created because this local repo has no commits. "
            "Make an initial commit first or use `!c start` to let an agent create one.",
        )
        return

    create_args = [
        "gh",
        "repo",
        "create",
        repo_name,
        visibility,
        "--source",
        ".",
        "--remote",
        "origin",
        "--push",
    ]
    create_out, create_err = await run_limited_command(repo_path, create_args)
    if create_err:
        await router.reply(sink, f"gh repo create failed: {_format_command_failure(create_out, create_err)}")
        return
    await router.reply(sink, "GitHub repo created and remote wired.")


def _gh_clone_completion_hint(fields: list[str]) -> str:
    """Return a clone completion hint for gh clone-style commands."""
    repo_name = _infer_cloned_repo_name(fields)
    if repo_name:
        return f"Clone complete. Use `#code-{repo_name}` for prompts."
    return ""


def _infer_cloned_repo_name(fields: list[str]) -> str:
    """Infer a repo name from gh clone arguments."""
    if len(fields) < 3:
        return ""
    if fields[0] == "repo" and fields[1] == "clone":
        if len(fields) >= 4 and not fields[3].startswith("-"):
            return _normalize_repo_hint(fields[3])
        return _normalize_repo_hint(fields[2])
    if fields[0] == "repo" and fields[1] == "create" and "--clone" in fields:
        for token in fields[2:]:
            if token.startswith("-"):
                continue
            return _normalize_repo_hint(token)
    return ""


def _normalize_repo_hint(token: str) -> str:
    candidate = token.strip().rstrip("/")
    if not candidate:
        return ""
    if candidate.endswith(".git"):
        candidate = candidate[: -len(".git")]
    if ":" in candidate and "/" in candidate:
        candidate = candidate.rsplit(":", 1)[1]
    if "/" in candidate:
        candidate = candidate.rsplit("/", 1)[1]
    if not candidate:
        return ""
    try:
        return pathutil.normalize_repo_name(candidate)
    except ValueError:
        return ""


async def _ensure_git_repo(router: "Router", sink: ResponseSink, repo_path: str) -> bool:
    out, err = await run_limited_command(repo_path, ["git", "rev-parse", "--is-inside-work-tree"])
    if err or _clean_output(out).lower() != "true":
        await router.reply(
            sink,
            "Repository is not initialized with git. Run `!c create` first or initialize the repo before using `!c gh-create`.",
        )
        return False
    return True


async def _gh_owner(router: "Router", sink: ResponseSink, repo_path: str) -> str:
    out, err = await run_limited_command(repo_path, ["gh", "api", "user", "--jq", ".login"])
    if err:
        details = _format_command_failure(out, err)
        if isinstance(err, FileNotFoundError):
            await router.reply(sink, "GitHub CLI (`gh`) is not installed or is not available in PATH.")
        else:
            await router.reply(sink, f"GitHub CLI is not authenticated or unavailable: {details}")
        return ""
    owner = _clean_output(out)
    if not owner:
        await router.reply(sink, "GitHub CLI did not return a username. Run `gh auth login` and try again.")
        return ""
    return owner.splitlines()[0].strip()


def _clean_output(text: str) -> str:
    return strip_control_codes(text or "").strip()


def _format_command_failure(out: str, err: Exception) -> str:
    details = trim_output(_clean_output(out), 20, 2000)
    return details or str(err)
