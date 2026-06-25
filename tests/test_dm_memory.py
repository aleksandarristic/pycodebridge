from codebridge import config as cfgmod
from codebridge.routing.router import Router
from codebridge.services.dm_memory import DmMemoryService
from codebridge.sessions.coordinator import SessionCoordinator
from codebridge.sessions.state import Store


class _FakeAudit:
    redactor = None


class _FakeLogger:
    def warning(self, name: str, extra=None):
        _ = (name, extra)


def _config(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path / "code")
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "state" / "logs")
    return cfg


def test_dm_memory_uses_default_dir_and_missing_read_fallback(tmp_path):
    cfg = _config(tmp_path)
    service = DmMemoryService(cfg)

    assert service.memory_dir == tmp_path / "state" / "dm-memory"
    assert service.get_path("user-1") == service.memory_dir / "user-1.md"
    assert service.exists("user-1") is False
    assert service.read("user-1") == ""


def test_dm_memory_uses_configured_dir_and_stable_safe_path(tmp_path):
    cfg = _config(tmp_path)
    cfg.dm_assistant.memory_dir = str(tmp_path / "custom-memory")
    service = DmMemoryService(cfg)

    first = service.get_path("user:/1")
    second = service.get_path("user:/1")
    assert first == second
    assert first == tmp_path / "custom-memory" / "user_1.md"

    first.write_text("prefers concise replies", encoding="utf-8")
    assert service.exists("user:/1") is True
    assert service.read("user:/1") == "prefers concise replies"


def test_router_exposes_dm_memory_service(tmp_path):
    cfg = _config(tmp_path)
    store = Store(cfg.state.data_dir)
    coordinator = SessionCoordinator(store, cfg)

    router = Router(cfg, store, _FakeAudit(), object(), coordinator, _FakeLogger())

    assert isinstance(router.dm_memory, DmMemoryService)
