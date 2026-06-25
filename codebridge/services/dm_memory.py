"""Per-user memory files for the DM assistant."""

from __future__ import annotations

import re
from pathlib import Path

from .. import config as cfgmod

_SAFE_USER_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


class DmMemoryService:
    """Resolve and read per-user markdown memory files."""

    def __init__(self, cfg: cfgmod.Config) -> None:
        base = cfg.dm_assistant.memory_dir or str(Path(cfg.state.data_dir) / "dm-memory")
        self.memory_dir = Path(base)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def get_path(self, user_id: str) -> Path:
        safe = _SAFE_USER_ID_RE.sub("_", (user_id or "").strip()).strip("._-")
        if not safe:
            safe = "unknown"
        return self.memory_dir / f"{safe}.md"

    def exists(self, user_id: str) -> bool:
        return self.get_path(user_id).is_file()

    def read(self, user_id: str) -> str:
        path = self.get_path(user_id)
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")
