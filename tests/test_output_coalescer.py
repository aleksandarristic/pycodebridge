"""Tests for the streamed-output coalescer used by run_codex."""

import asyncio

from codebridge.routing.router import _OutputCoalescer


def _collector():
    sent: list[str] = []

    async def relay(text: str) -> None:
        sent.append(text)

    return sent, relay


def test_coalescer_batches_until_explicit_flush():
    sent, relay = _collector()

    async def run() -> None:
        c = _OutputCoalescer(relay, max_chars=1000, flush_seconds=10.0)
        await c.add("a")
        await c.add("b")
        await c.add("c")
        assert sent == []  # buffered, idle window not elapsed
        await c.flush()

    asyncio.run(run())
    assert sent == ["a\nb\nc"]


def test_coalescer_flushes_when_size_cap_exceeded():
    sent, relay = _collector()

    async def run() -> None:
        c = _OutputCoalescer(relay, max_chars=5, flush_seconds=10.0)
        await c.add("abc")  # size 3
        await c.add("de")  # 3 + 1 + 2 = 6 > 5 -> flush "abc", then buffer "de"
        await c.flush()

    asyncio.run(run())
    assert sent == ["abc", "de"]


def test_coalescer_idle_timer_flushes_without_explicit_flush():
    sent, relay = _collector()

    async def run() -> None:
        c = _OutputCoalescer(relay, max_chars=1000, flush_seconds=0.05)
        await c.add("x")
        await asyncio.sleep(0.2)
        assert sent == ["x"]

    asyncio.run(run())


def test_coalescer_zero_window_relays_immediately():
    sent, relay = _collector()

    async def run() -> None:
        c = _OutputCoalescer(relay, max_chars=1000, flush_seconds=0.0)
        await c.add("a")
        await c.add("b")

    asyncio.run(run())
    assert sent == ["a", "b"]


def test_coalescer_flush_is_noop_when_empty():
    sent, relay = _collector()

    async def run() -> None:
        c = _OutputCoalescer(relay, max_chars=1000, flush_seconds=10.0)
        await c.flush()

    asyncio.run(run())
    assert sent == []


def test_coalescer_can_prefix_buffered_split_prompt():
    sent, relay = _collector()

    async def run() -> None:
        c = _OutputCoalescer(relay, max_chars=1000, flush_seconds=10.0)
        await c.add("Hello! How can I help you with the s")
        assert await c.prefix_buffer("Gemini asks: ") is True
        await c.add("ajt repository today?")
        await c.flush()

    asyncio.run(run())
    assert sent == ["Gemini asks: Hello! How can I help you with the s\najt repository today?"]


def test_coalescer_prefix_buffer_noops_when_empty():
    sent, relay = _collector()

    async def run() -> None:
        c = _OutputCoalescer(relay, max_chars=1000, flush_seconds=10.0)
        assert await c.prefix_buffer("Gemini asks: ") is False
        await c.flush()

    asyncio.run(run())
    assert sent == []
