import asyncio
import json
import time
from dataclasses import dataclass

from codebridge.health import collect_health_payload, parse_health_bind, start_health_server


@dataclass
class _Status:
    status: str


class _FakeChannel:
    def __init__(self, sessions: int) -> None:
        self.sessions = {f"s{i}": object() for i in range(sessions)}


class _FakeState:
    def __init__(self) -> None:
        self.channels = {"a": _FakeChannel(2), "b": _FakeChannel(1)}


class _StateStore:
    def load(self):
        return _FakeState()


class _Coordinator:
    async def snapshot_all(self):
        return {
            "a": [_Status("running"), _Status("queued"), _Status("queued")],
            "b": [_Status("running")],
        }


class _Router:
    def __init__(self, error_log: str = "") -> None:
        self.state = _StateStore()
        self.coordinator = _Coordinator()
        self._codex_error_log_path = error_log


class _Logger:
    def __init__(self) -> None:
        self.events: list[str] = []

    def info(self, name: str, extra=None) -> None:
        _ = extra
        self.events.append(name)


def test_parse_health_bind():
    assert parse_health_bind("8080") == ("127.0.0.1", 8080)
    assert parse_health_bind("0.0.0.0:9000") == ("0.0.0.0", 9000)


def test_collect_health_payload(tmp_path):
    log_path = tmp_path / "codex_errors.log"
    log_path.write_text(
        "\n".join(
            [
                json.dumps({"timestamp": "2026-01-01T00:00:00+00:00", "note": "x"}),
                json.dumps({"timestamp": "2026-01-01T01:00:00+00:00", "note": "y"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    router = _Router(str(log_path))

    async def run():
        payload = await collect_health_payload(router, time.monotonic() - 5)
        assert payload["status"] == "ok"
        assert payload["channels"] == 2
        assert payload["sessions"] == 3
        assert payload["queue"]["running"] == 2
        assert payload["queue"]["queued"] == 2
        assert payload["recent_errors"]["count"] == 2
        assert payload["recent_errors"]["last_timestamp"] == "2026-01-01T01:00:00+00:00"
        assert payload["uptime_seconds"] >= 4

    asyncio.run(run())


def test_health_server_serves_payload():
    router = _Router()
    logger = _Logger()

    async def run():
        server = await start_health_server(router, logger, "127.0.0.1:0", "/healthz")
        sock = server.sockets[0]
        host, port = sock.getsockname()[0], sock.getsockname()[1]
        reader, writer = await asyncio.open_connection(host, port)
        writer.write(b"GET /healthz HTTP/1.1\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        data = await reader.read(8192)
        writer.close()
        await writer.wait_closed()
        server.close()
        await server.wait_closed()
        text = data.decode("utf-8", errors="replace")
        assert "200 OK" in text
        assert '"status": "ok"' in text

    asyncio.run(run())
