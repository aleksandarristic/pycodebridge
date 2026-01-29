import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

SAFE_SEG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass
class Entry:
    seq: str
    channel_id: str
    session: str
    thread_id: str
    codex_path: str
    discord_path: str
    stderr_path: str

    _codex_file: Optional[Any] = None
    _discord_file: Optional[Any] = None
    _stderr_file: Optional[Any] = None

    def append_codex_line(self, line: str) -> None:
        if self._codex_file:
            self._codex_file.write(line + "\n")
            self._codex_file.flush()

    def append_discord_out(self, text: str) -> None:
        if self._discord_file:
            self._discord_file.write(text + "\n")
            self._discord_file.flush()

    def append_stderr(self, text: str) -> None:
        if self._stderr_file:
            self._stderr_file.write(text + "\n")
            self._stderr_file.flush()

    def close(self) -> None:
        for f in (self._codex_file, self._discord_file, self._stderr_file):
            if f:
                try:
                    f.flush()
                    f.close()
                except Exception:
                    pass


@dataclass
class Summary:
    seq: str
    channel_id: str
    session: str
    thread_id: str
    request: Dict[str, Any]
    path: str


class Logger:
    def __init__(self, base_dir: str) -> None:
        if not base_dir:
            raise ValueError("log dir is required")
        os.makedirs(base_dir, exist_ok=True)
        self.base_dir = base_dir

    def start(self, channel_id: str, session: str, thread_id: str, request: Any) -> Entry:
        session = session or "default"
        channel_safe = _safe_segment(channel_id, "channel")
        session_safe = _safe_segment(session, "default")
        thread_safe = _safe_segment(thread_id, "pending")

        entry_dir = os.path.join(self.base_dir, channel_safe, session_safe, thread_safe)
        os.makedirs(entry_dir, exist_ok=True)

        seq = _next_seq(entry_dir)
        request_path = os.path.join(entry_dir, f"{seq}.request.json")
        _write_json(request_path, request)

        codex_path = os.path.join(entry_dir, f"{seq}.codex.jsonl")
        discord_path = os.path.join(entry_dir, f"{seq}.discord_out.txt")
        stderr_path = os.path.join(entry_dir, f"{seq}.codex.stderr.txt")

        entry = Entry(
            seq=seq,
            channel_id=channel_id,
            session=session,
            thread_id=thread_id,
            codex_path=codex_path,
            discord_path=discord_path,
            stderr_path=stderr_path,
        )
        entry._codex_file = open(codex_path, "w", encoding="utf-8")
        entry._discord_file = open(discord_path, "w", encoding="utf-8")
        entry._stderr_file = open(stderr_path, "w", encoding="utf-8")
        return entry

    def summaries(self, channel_id: str, session: str, limit: int) -> list[Summary]:
        summaries: list[Summary] = []
        if channel_id:
            channel_id = _safe_segment(channel_id, "channel")
        if session:
            session = _safe_segment(session, "default")

        channels = [channel_id] if channel_id else [d for d in os.listdir(self.base_dir) if os.path.isdir(os.path.join(self.base_dir, d))]
        for ch in channels:
            channel_dir = os.path.join(self.base_dir, ch)
            if not os.path.isdir(channel_dir):
                continue
            session_dirs = [session] if session else [d for d in os.listdir(channel_dir) if os.path.isdir(os.path.join(channel_dir, d))]
            for sess in session_dirs:
                sess_dir = os.path.join(channel_dir, sess)
                if not os.path.isdir(sess_dir):
                    continue
                for thread_id in os.listdir(sess_dir):
                    thread_dir = os.path.join(sess_dir, thread_id)
                    if not os.path.isdir(thread_dir):
                        continue
                    for fname in os.listdir(thread_dir):
                        if not fname.endswith(".request.json"):
                            continue
                        path = os.path.join(thread_dir, fname)
                        try:
                            with open(path, "r", encoding="utf-8") as f:
                                req = json.load(f)
                            seq = fname.split(".")[0]
                            summaries.append(Summary(seq, ch, sess, thread_id, req, thread_dir))
                        except Exception:
                            continue

        summaries.sort(key=lambda s: s.seq, reverse=True)
        if limit > 0:
            summaries = summaries[:limit]
        return summaries


def _next_seq(entry_dir: str) -> str:
    latest_path = os.path.join(entry_dir, ".latest")
    next_val = 1
    if os.path.exists(latest_path):
        try:
            with open(latest_path, "r", encoding="utf-8") as f:
                val = int(f.read().strip() or 0)
                next_val = val + 1
        except Exception:
            pass
    if next_val == 1:
        for fname in os.listdir(entry_dir):
            if fname.endswith(".request.json"):
                try:
                    val = int(fname.split(".")[0])
                    next_val = max(next_val, val + 1)
                except Exception:
                    continue
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(str(next_val))
    return f"{next_val:06d}"


def _write_json(path: str, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _safe_segment(val: str, fallback: str) -> str:
    if not val:
        val = fallback
    if SAFE_SEG_RE.match(val):
        return val
    digest = hashlib.sha1(val.encode("utf-8")).hexdigest()[:12]
    return f"{fallback}-{digest}"

