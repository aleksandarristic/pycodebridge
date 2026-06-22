import asyncio

from codebridge import config as cfgmod
from codebridge.handlers import core
from codebridge.platform.transport import Capabilities, MessageEvent
from codebridge.routing.router import Router
from codebridge.sessions.coordinator import SessionCoordinator
from codebridge.sessions.state import Store


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _FakeSink:
    def __init__(self, channel_id: str = "chan") -> None:
        self.channel_id = channel_id
        self.messages: list[str] = []
        self.forbidden: list[str] = []

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        self.messages.append(content)

    def capabilities(self) -> Capabilities:
        return Capabilities(threads=True, uploads=True, downloads=True, typing=True)

    def typing(self):
        return _FakeTyping()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        return None

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        return None


class _FakeTyping:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeLogger:
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def error(self, *a, **kw): pass


class _FakeAudit:
    def log(self, *a, **kw): pass
    def append_output(self, *a, **kw): pass


class _FakeRunner:
    pass


class _FakePinnedMessage:
    def __init__(self, msg_id: str) -> None:
        self.id = msg_id
        self.unpinned = False

    async def unpin(self) -> None:
        self.unpinned = True


class _FakePermissions:
    def __init__(self) -> None:
        self.view_channel = False  # private from @everyone


class _FakeGuild:
    def __init__(self) -> None:
        self.default_role = object()


class _FakeChannel:
    def __init__(self, name: str = "code-repo", pins_list: list | None = None) -> None:
        self.name = name
        self.id = name
        self._pins = pins_list or []
        self.guild = _FakeGuild()

    def permissions_for(self, role) -> _FakePermissions:
        _ = role
        return _FakePermissions()

    async def pins(self) -> list[_FakePinnedMessage]:
        return list(self._pins)


class _FakeRouter:
    def __init__(self, *, guild_fn=None) -> None:
        self._guild_text_channels_fn = guild_fn
        from codebridge import config as cfgmod
        self.cfg = cfgmod.Config()
        self.cfg.discord.channel_name_regex = r"^code-([A-Za-z0-9._-]+)$"
        self.cfg.discord._compiled_regex = None

    async def reply(self, sink: _FakeSink, text: str) -> None:
        sink.messages.append(text)

    async def reply_forbidden(self, sink: _FakeSink, text: str) -> None:
        sink.forbidden.append(text)

    def channel_regex(self):
        import re
        return re.compile(self.cfg.discord.channel_name_regex)

    def cfg_channel_regex(self):
        return self.cfg.channel_regex()

    def logger(self):
        return _FakeLogger()


# Patch router.cfg.channel_regex() into the real call path
class _RouterWithRegex(_FakeRouter):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.logger = _FakeLogger()

    def channel_regex(self):
        import re
        return re.compile(r"^code-([A-Za-z0-9._-]+)$")


def _make_event(channel=None) -> MessageEvent:
    class _Msg:
        pass
    msg = _Msg()
    msg.channel = channel
    return MessageEvent(
        platform="discord",
        content="!c unpin",
        channel_id="chan",
        channel_name="code-repo",
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        raw_event=msg,
    )


def _make_event_no_raw() -> MessageEvent:
    return MessageEvent(
        platform="discord",
        content="!c unpin",
        channel_id="chan",
        channel_name="code-repo",
        author_id="user",
        author_is_bot=False,
        is_dm=False,
    )


# ---------------------------------------------------------------------------
# handle_unpin — in-channel
# ---------------------------------------------------------------------------

def test_unpin_no_raw_event_replies_unsupported():
    async def run():
        router = _RouterWithRegex()
        sink = _FakeSink()
        event = _make_event_no_raw()
        await core.handle_unpin(router, event, sink)
        assert sink.forbidden
        assert "not supported" in sink.forbidden[0]

    asyncio.run(run())


def test_unpin_channel_without_pins_method_replies_unsupported():
    async def run():
        class _NoPin:
            pass
        router = _RouterWithRegex()
        sink = _FakeSink()
        event = _make_event(channel=_NoPin())
        await core.handle_unpin(router, event, sink)
        assert sink.forbidden
        assert "not supported" in sink.forbidden[0]

    asyncio.run(run())


def test_unpin_zero_pins_replies_nothing_to_remove():
    async def run():
        router = _RouterWithRegex()
        sink = _FakeSink()
        event = _make_event(channel=_FakeChannel(pins_list=[]))
        await core.handle_unpin(router, event, sink)
        assert sink.messages
        assert "Nothing to remove" in sink.messages[0]
        assert "0 pins" in sink.messages[0]

    asyncio.run(run())


def test_unpin_one_pin_replies_nothing_to_remove():
    async def run():
        router = _RouterWithRegex()
        sink = _FakeSink()
        msg = _FakePinnedMessage("1")
        event = _make_event(channel=_FakeChannel(pins_list=[msg]))
        await core.handle_unpin(router, event, sink)
        assert sink.messages
        assert "Nothing to remove" in sink.messages[0]
        assert not msg.unpinned

    asyncio.run(run())


def test_unpin_multiple_pins_removes_all_but_last():
    async def run():
        router = _RouterWithRegex()
        sink = _FakeSink()
        msgs = [_FakePinnedMessage(str(i)) for i in range(4)]
        event = _make_event(channel=_FakeChannel(pins_list=msgs))
        await core.handle_unpin(router, event, sink)
        assert msgs[0].unpinned
        assert msgs[1].unpinned
        assert msgs[2].unpinned
        assert not msgs[3].unpinned
        assert sink.messages
        assert "Removed 3" in sink.messages[0]

    asyncio.run(run())


def test_unpin_two_pins_removes_first_keeps_last():
    async def run():
        router = _RouterWithRegex()
        sink = _FakeSink()
        old_msg = _FakePinnedMessage("old")
        new_msg = _FakePinnedMessage("new")
        event = _make_event(channel=_FakeChannel(pins_list=[old_msg, new_msg]))
        await core.handle_unpin(router, event, sink)
        assert old_msg.unpinned
        assert not new_msg.unpinned
        assert sink.messages
        assert "Removed 1" in sink.messages[0]

    asyncio.run(run())


# ---------------------------------------------------------------------------
# handle_unpin_all_channels — DM admin
# ---------------------------------------------------------------------------

def test_unpin_all_no_fn_replies_unavailable():
    async def run():
        router = _RouterWithRegex(guild_fn=None)
        sink = _FakeSink()
        await core.handle_unpin_all_channels(router, sink)
        assert sink.forbidden
        assert "not available" in sink.forbidden[0]

    asyncio.run(run())


def test_unpin_all_no_matching_channels_replies_none_found():
    async def run():
        async def _channels():
            return [_FakeChannel(name="general", pins_list=[_FakePinnedMessage("1")])]

        router = _RouterWithRegex(guild_fn=_channels)
        router.cfg.channel_regex = lambda: __import__("re").compile(r"^code-([A-Za-z0-9._-]+)$")
        sink = _FakeSink()
        await core.handle_unpin_all_channels(router, sink)
        assert sink.messages
        assert "No matching channels" in sink.messages[0]

    asyncio.run(run())


def test_unpin_all_single_pin_channels_are_skipped():
    async def run():
        ch = _FakeChannel(name="code-repo", pins_list=[_FakePinnedMessage("only")])

        async def _channels():
            return [ch]

        router = _RouterWithRegex(guild_fn=_channels)
        sink = _FakeSink()
        await core.handle_unpin_all_channels(router, sink)
        assert sink.messages
        assert "1 pin" in sink.messages[0]
        assert "nothing to remove" in sink.messages[0]

    asyncio.run(run())


def test_unpin_all_removes_old_pins_across_channels():
    async def run():
        msgs_a = [_FakePinnedMessage(f"a{i}") for i in range(3)]
        msgs_b = [_FakePinnedMessage(f"b{i}") for i in range(2)]
        ch_a = _FakeChannel(name="code-api", pins_list=msgs_a)
        ch_b = _FakeChannel(name="code-web", pins_list=msgs_b)
        ch_ignored = _FakeChannel(name="general", pins_list=[_FakePinnedMessage("x")])

        async def _channels():
            return [ch_a, ch_b, ch_ignored]

        router = _RouterWithRegex(guild_fn=_channels)
        sink = _FakeSink()
        await core.handle_unpin_all_channels(router, sink)

        assert msgs_a[0].unpinned and msgs_a[1].unpinned
        assert not msgs_a[2].unpinned
        assert msgs_b[0].unpinned
        assert not msgs_b[1].unpinned
        assert sink.messages
        report = sink.messages[0]
        assert "code-api" in report
        assert "code-web" in report
        assert "general" not in report

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Integration: in-channel !c unpin command dispatch
# ---------------------------------------------------------------------------

def _build_router(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user"]
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    store = Store(cfg.state.data_dir)
    coordinator = SessionCoordinator(store, cfg)
    router = Router(cfg, store, _FakeAudit(), _FakeRunner(), coordinator, _FakeLogger())
    return router


def test_integration_unpin_command_in_channel(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router = _build_router(tmp_path)
    msgs = [_FakePinnedMessage(str(i)) for i in range(3)]
    channel = _FakeChannel(name="code-repo", pins_list=msgs)
    sink = _FakeSink()

    class _Msg:
        pass
    raw = _Msg()
    raw.channel = channel

    event = MessageEvent(
        platform="discord",
        content="!c unpin",
        channel_id="chan",
        channel_name="code-repo",
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        guild_id="guild1",
        raw_event=raw,
    )

    asyncio.run(router.handle_message(event, sink))
    all_messages = " ".join(sink.messages)
    assert "Removed 2" in all_messages
    assert msgs[0].unpinned and msgs[1].unpinned
    assert not msgs[2].unpinned


def test_integration_unpin_dm_all_channels(tmp_path):
    router = _build_router(tmp_path)
    router.cfg.discord.dm_admin_enabled = True
    router.cfg.discord.dm_admin_user_ids = ["user"]
    msgs = [_FakePinnedMessage(str(i)) for i in range(3)]
    channel = _FakeChannel(name="code-repo", pins_list=msgs)

    async def _channels():
        return [channel]

    router.set_guild_text_channels_fn(_channels)

    sink = _FakeSink(channel_id="dm-1")
    cfg = router.cfg

    event = MessageEvent(
        platform="discord",
        content="!c unpin",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    asyncio.run(router.handle_message(event, sink))
    all_messages = " ".join(sink.messages)
    assert "code-repo" in all_messages
    assert msgs[0].unpinned and msgs[1].unpinned
    assert not msgs[2].unpinned
