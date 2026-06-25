from types import SimpleNamespace

from codebridge import config as cfgmod
from codebridge.platform.transport import MessageEvent
from codebridge.services.dm_assistant import build_dm_assistant_prompt, resolve_dm_assistant_repo_path
from codebridge.services.dm_memory import DmMemoryService
from codebridge.sessions.state import ChannelState, FileState, SessionState


class _FakeState:
    def __init__(self, state: FileState) -> None:
        self._state = state

    def load(self) -> FileState:
        return self._state


def _event(user_id: str = "user") -> MessageEvent:
    return MessageEvent(
        platform="discord",
        content="hello",
        channel_id="dm-chan",
        channel_name="",
        author_id=user_id,
        author_is_bot=False,
        is_dm=True,
    )


def _router(tmp_path, state: FileState | None = None):
    code_root = tmp_path / "code"
    data_dir = tmp_path / "state"
    code_root.mkdir()
    data_dir.mkdir()
    (code_root / "pycodebridge").mkdir()
    (code_root / "alpha").mkdir()
    (code_root / "beta").mkdir()

    cfg = cfgmod.Config()
    cfg.codex.code_root = str(code_root)
    cfg.state.data_dir = str(data_dir)
    cfg.state.log_dir = str(data_dir / "logs")
    cfg.agent.default_backend = "codex"
    return SimpleNamespace(
        cfg=cfg,
        dm_memory=DmMemoryService(cfg),
        state=_FakeState(state or FileState()),
    )


def test_build_dm_assistant_prompt_includes_repos_sessions_and_memory_path(tmp_path):
    state = FileState(
        channels={
            "chan": ChannelState(
                sessions={
                    "default": SessionState(
                        repo_name="alpha",
                        repo_path="/tmp/alpha",
                        thread_id="thread-1",
                        backend="claude",
                    )
                }
            )
        }
    )
    router = _router(tmp_path, state)

    prompt = build_dm_assistant_prompt(router, _event())

    assert f"pycodebridge repo at {tmp_path / 'code' / 'pycodebridge'}" in prompt
    assert "- README.md" in prompt
    assert "- docs/" in prompt
    assert "- alpha" in prompt
    assert "- beta" in prompt
    assert "- pycodebridge" in prompt
    assert "chan -> default: alpha (claude, known)" in prompt
    assert "## Your memory for this user:" not in prompt
    assert str(tmp_path / "state" / "dm-memory" / "user.md") in prompt
    assert len(prompt.split()) < 400


def test_build_dm_assistant_prompt_includes_memory_when_present(tmp_path):
    router = _router(tmp_path)
    router.dm_memory.get_path("user").write_text("Likes short status updates.", encoding="utf-8")

    prompt = build_dm_assistant_prompt(router, _event())

    assert "## Your memory for this user:" in prompt
    assert "Likes short status updates." in prompt


def test_build_dm_assistant_prompt_uses_custom_template_variables(tmp_path):
    router = _router(tmp_path)
    router.cfg.dm_assistant.start_prompt = "Repo={{REPO_PATH}} Memory={{MEMORY_FILE}} User={{USER_ID}}"

    prompt = build_dm_assistant_prompt(router, _event("abc"))

    assert f"Repo={tmp_path / 'code' / 'pycodebridge'}" in prompt
    assert f"Memory={tmp_path / 'state' / 'dm-memory' / 'abc.md'}" in prompt
    assert "User=abc" in prompt


def test_resolve_dm_assistant_repo_path_requires_managed_pycodebridge_repo(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path / "missing")
    router = SimpleNamespace(cfg=cfg)

    try:
        resolve_dm_assistant_repo_path(router)
        assert False, "expected FileNotFoundError"
    except FileNotFoundError as exc:
        assert "pycodebridge repo" in str(exc)
