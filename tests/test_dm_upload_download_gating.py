import asyncio
from dataclasses import dataclass

from codebridge import config as cfgmod
from codebridge.services.file_transfer import FileTransferService
from codebridge.platform.transport import Attachment, Capabilities, MessageEvent


class _FakeSink:
    def __init__(self, caps: Capabilities) -> None:
        self._caps = caps
        self.sent = []
        self.files = []
        self.channel_id = "dm"

    def capabilities(self) -> Capabilities:
        return self._caps

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        _ = (thread_id, reply_to_id)
        self.sent.append(content)

    def typing(self):
        return _FakeAsyncContext()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        return None

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        _ = (thread_id, reply_to_id)
        self.files.append((path, filename))


class _FakeAsyncContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


@dataclass(frozen=True)
class _Saved:
    path: str


async def _save_to(saved: list[_Saved], path: str) -> None:
    saved.append(_Saved(path=path))


def _event_with_attachment() -> MessageEvent:
    saved: list[_Saved] = []
    attachment = Attachment(
        filename="note.txt",
        size=5,
        content_type="text/plain",
        save=lambda path: _save_to(saved, path),
    )
    event = MessageEvent(
        platform="discord",
        content="",
        channel_id="dm",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
        attachments=[attachment],
    )
    return event


def test_upload_gated_when_capability_false(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    cfg.files.max_upload_mb = 1

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    service = FileTransferService(cfg, logger=_FakeLogger())
    sink = _FakeSink(Capabilities(uploads=False))
    event = _event_with_attachment()

    async def run():
        await service.handle_upload_request(event, sink, "repo", str(repo), _reply_forbidden, _reply)

    asyncio.run(run())
    assert "Uploads are not supported" in sink.sent[0]


def test_download_gated_when_capability_false(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    target = repo / "note.txt"
    target.write_text("hi")

    service = FileTransferService(cfg, logger=_FakeLogger())
    sink = _FakeSink(Capabilities(downloads=False))

    async def run():
        await service.handle_download(sink, str(repo), "note.txt", _reply_forbidden)

    asyncio.run(run())
    assert "Downloads are not supported" in sink.sent[0]


def test_download_allowed_when_capability_true(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    target = repo / "note.txt"
    target.write_text("hi")

    service = FileTransferService(cfg, logger=_FakeLogger())
    sink = _FakeSink(Capabilities(downloads=True))

    async def run():
        await service.handle_download(sink, str(repo), "note.txt", _reply_forbidden)

    asyncio.run(run())
    assert sink.files == [(str(target), "note.txt")]


def test_upload_sanitizes_attachment_filename_before_save(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    cfg.files.max_upload_mb = 1

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "uploads").mkdir()

    saved: list[_Saved] = []
    attachment = Attachment(
        filename="../outside.txt",
        size=5,
        content_type="text/plain",
        save=lambda path: _save_to(saved, path),
    )
    request = MessageEvent(
        platform="discord",
        content="",
        channel_id="dm",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
        attachments=[attachment],
    )
    response = MessageEvent(
        platform="discord",
        content="uploads/",
        channel_id="dm",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    service = FileTransferService(cfg, logger=_FakeLogger())
    sink = _FakeSink(Capabilities(uploads=True))

    async def run():
        await service.handle_upload_request(request, sink, "repo", str(repo), _reply_forbidden, _reply)
        handled = await service.handle_pending_upload_response(
            response,
            sink,
            "repo",
            "!c",
            _reply_forbidden,
            _reply,
        )
        assert handled is True

    asyncio.run(run())
    assert saved, "expected uploaded file to be saved"
    saved_path = saved[0].path
    assert saved_path == str(repo / "uploads" / "outside.txt")


class _FakeLogger:
    def info(self, name: str, extra=None):
        return None


def _reply_forbidden(sink: _FakeSink, msg: str):
    return sink.send(msg)


def _reply(sink: _FakeSink, msg: str):
    return sink.send(msg)
