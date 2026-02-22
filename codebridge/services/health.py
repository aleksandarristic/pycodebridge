"""Lightweight HTTP health endpoint for operational checks."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit


def parse_health_bind(bind: str) -> tuple[str, int]:
    """Parse a host:port (or port-only) bind string."""
    raw = (bind or "").strip()
    if not raw:
        raise ValueError("runtime.health_bind is empty")
    if raw.isdigit():
        return "127.0.0.1", int(raw)
    if ":" not in raw:
        raise ValueError("runtime.health_bind must be '<host>:<port>' or '<port>'")
    host, port_s = raw.rsplit(":", 1)
    host = host.strip() or "127.0.0.1"
    try:
        port = int(port_s)
    except ValueError as exc:
        raise ValueError("runtime.health_bind port must be numeric") from exc
    if port < 0 or port > 65535:
        raise ValueError("runtime.health_bind port must be in 0..65535")
    return host, port


async def collect_health_payload(router: Any, started_monotonic: float) -> dict[str, Any]:
    """Build a JSON-serializable health payload."""
    state = router.state.load()
    channel_count = len(state.channels)
    session_count = sum(len(ch.sessions) for ch in state.channels.values())
    snapshot = await router.coordinator.snapshot_all()
    running = sum(1 for statuses in snapshot.values() for st in statuses if st.status == "running")
    queued = sum(1 for statuses in snapshot.values() for st in statuses if st.status == "queued")
    recent_error_count, last_error_at = _recent_error_metrics(getattr(router, "_codex_error_log_path", ""))
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": int(max(0.0, time.monotonic() - started_monotonic)),
        "channels": channel_count,
        "sessions": session_count,
        "queue": {
            "running": running,
            "queued": queued,
        },
        "recent_errors": {
            "count": recent_error_count,
            "last_timestamp": last_error_at,
        },
    }


async def start_health_server(
    router: Any,
    logger: Any,
    bind: str,
    path: str = "/healthz",
    started_monotonic: float | None = None,
) -> asyncio.AbstractServer:
    """Start a tiny HTTP server that serves health payloads."""
    host, port = parse_health_bind(bind)
    endpoint_path = (path or "/healthz").strip() or "/healthz"
    if not endpoint_path.startswith("/"):
        endpoint_path = "/" + endpoint_path
    started_at = started_monotonic if started_monotonic is not None else time.monotonic()

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        status = "200 OK"
        body = b""
        content_type = "application/json"
        try:
            raw = await reader.read(8192)
            request_line = raw.splitlines()[0].decode("utf-8", errors="replace") if raw else ""
            parts = request_line.split()
            method = parts[0] if len(parts) >= 1 else ""
            target = parts[1] if len(parts) >= 2 else "/"
            req_path = urlsplit(target).path
            if method != "GET":
                status = "405 Method Not Allowed"
                body = b'{"status":"error","detail":"method_not_allowed"}'
            elif req_path != endpoint_path:
                status = "404 Not Found"
                body = b'{"status":"error","detail":"not_found"}'
            else:
                payload = await collect_health_payload(router, started_at)
                body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        except Exception:
            status = "500 Internal Server Error"
            body = b'{"status":"error","detail":"health_failure"}'
        try:
            writer.write(
                (
                    f"HTTP/1.1 {status}\r\n"
                    f"Content-Type: {content_type}\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("ascii")
                + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(_handler, host=host, port=port)
    logger.info("health.server.started", extra={"bind": f"{host}:{port}", "path": endpoint_path})
    return server


def _recent_error_metrics(path: str, limit: int = 200) -> tuple[int, str]:
    if not path or not os.path.exists(path):
        return 0, ""
    count = 0
    last_ts = ""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        for line in lines[-limit:]:
            text = (line or "").strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except Exception:
                continue
            count += 1
            ts = str(payload.get("timestamp") or "").strip()
            if ts:
                last_ts = ts
    except Exception:
        return 0, ""
    return count, last_ts
