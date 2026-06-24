import asyncio
from dataclasses import dataclass
import os

import pytest

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
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("saved")


def _attachment(filename: str = "note.txt", size: int = 5, save=None) -> Attachment:
    saved: list[_Saved] = []
    return Attachment(
        filename=filename,
        size=size,
        content_type="text/plain",
        save=save or (lambda path: _save_to(saved, path)),
    )


def _event_with_attachments(attachments: list[Attachment], content: str = "") -> MessageEvent:
    return MessageEvent(
        platform="discord",
        content=content,
        channel_id="dm",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
        attachments=attachments,
    )


def _event_with_attachment() -> MessageEvent:
    saved: list[_Saved] = []
    attachment = Attachment(
        filename="note.txt",
        size=5,
        content_type="text/plain",
        save=lambda path: _save_to(saved, path),
    )
    return _event_with_attachments([attachment])


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


def test_upload_rejects_too_many_attachments(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    cfg.files.max_upload_mb = 1
    cfg.files.max_upload_count = 1

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    service = FileTransferService(cfg, logger=_FakeLogger())
    sink = _FakeSink(Capabilities(uploads=True))
    event = _event_with_attachments([_attachment("a.txt"), _attachment("b.txt")])

    async def run():
        await service.handle_upload_request(event, sink, "repo", str(repo), _reply_forbidden, _reply)

    asyncio.run(run())
    assert "Too many files (max 1)." in sink.sent[0]
    assert not service.has_pending_upload(event)


def test_upload_rejects_aggregate_size_over_limit(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    cfg.files.max_upload_mb = 1
    cfg.files.max_upload_total_mb = 1

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    service = FileTransferService(cfg, logger=_FakeLogger())
    sink = _FakeSink(Capabilities(uploads=True))
    event = _event_with_attachments([
        _attachment("a.txt", size=700 * 1024),
        _attachment("b.txt", size=700 * 1024),
    ])

    async def run():
        await service.handle_upload_request(event, sink, "repo", str(repo), _reply_forbidden, _reply)

    asyncio.run(run())
    assert "Total upload size too large (max 1MB)." in sink.sent[0]
    assert not service.has_pending_upload(event)


def test_upload_saves_single_attachment_to_requested_file_path(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    cfg.files.max_upload_mb = 1

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    request = _event_with_attachments([_attachment("note.txt")])
    response = MessageEvent(
        platform="discord",
        content="docs/readme.txt",
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
        handled = await service.handle_pending_upload_response(response, sink, "repo", "!c", _reply_forbidden, _reply)
        assert handled is True

    asyncio.run(run())
    assert (repo / "docs" / "readme.txt").read_text(encoding="utf-8") == "saved"
    assert "Saved 1 file(s):\ndocs/readme.txt" in sink.sent[-1]


def test_upload_requires_directory_for_multiple_attachments(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    cfg.files.max_upload_mb = 1

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    request = _event_with_attachments([_attachment("a.txt"), _attachment("b.txt")])
    response = MessageEvent(
        platform="discord",
        content="combined.txt",
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
        handled = await service.handle_pending_upload_response(response, sink, "repo", "!c", _reply_forbidden, _reply)
        assert handled is True

    asyncio.run(run())
    assert "Provide a directory path when uploading multiple files." in sink.sent[-1]
    assert not (repo / "combined.txt").exists()


def test_upload_saves_multiple_attachments_to_requested_directory(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    cfg.files.max_upload_mb = 1

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    request = _event_with_attachments([_attachment("a.txt"), _attachment("b.txt")])
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
        handled = await service.handle_pending_upload_response(response, sink, "repo", "!c", _reply_forbidden, _reply)
        assert handled is True

    asyncio.run(run())
    assert (repo / "uploads" / "a.txt").read_text(encoding="utf-8") == "saved"
    assert (repo / "uploads" / "b.txt").read_text(encoding="utf-8") == "saved"
    assert "Saved 2 file(s):" in sink.sent[-1]
    assert "uploads/a.txt" in sink.sent[-1]
    assert "uploads/b.txt" in sink.sent[-1]


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
    assert saved[0].path != str(repo / "uploads" / "outside.txt")
    assert (repo / "uploads" / "outside.txt").read_text(encoding="utf-8") == "saved"


def test_upload_rejects_destination_path_traversal(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    cfg.files.max_upload_mb = 1

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    request = _event_with_attachments([_attachment("note.txt")])
    response = MessageEvent(
        platform="discord",
        content="../outside.txt",
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
        handled = await service.handle_pending_upload_response(response, sink, "repo", "!c", _reply_forbidden, _reply)
        assert handled is True

    asyncio.run(run())
    assert "Invalid path:" in sink.sent[-1]
    assert not (tmp_path / "outside.txt").exists()


def test_upload_rejects_existing_symlink_destination(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    cfg.files.max_upload_mb = 1

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "real.txt").write_text("real", encoding="utf-8")
    try:
        os.symlink(repo / "real.txt", repo / "link.txt")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    request = _event_with_attachments([_attachment("note.txt")])
    response = MessageEvent(
        platform="discord",
        content="link.txt",
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
        handled = await service.handle_pending_upload_response(response, sink, "repo", "!c", _reply_forbidden, _reply)
        assert handled is True

    asyncio.run(run())
    assert "Upload destination is a symlink." in sink.sent[-1]
    assert (repo / "real.txt").read_text(encoding="utf-8") == "real"


def test_upload_rejects_symlink_parent_directory(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    cfg.files.max_upload_mb = 1

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "real").mkdir()
    try:
        os.symlink(repo / "real", repo / "linked")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    request = _event_with_attachments([_attachment("note.txt")])
    response = MessageEvent(
        platform="discord",
        content="linked/",
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
        handled = await service.handle_pending_upload_response(response, sink, "repo", "!c", _reply_forbidden, _reply)
        assert handled is True

    asyncio.run(run())
    assert "upload path contains a symlink" in sink.sent[-1]
    assert not (repo / "real" / "note.txt").exists()


def test_upload_finalization_does_not_overwrite_file_created_during_save(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    cfg.files.max_upload_mb = 1

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "uploads").mkdir()
    first_dest = repo / "uploads" / "note.txt"

    async def save_with_race(path: str) -> None:
        first_dest.write_text("existing", encoding="utf-8")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("saved")

    request = _event_with_attachments([_attachment("note.txt", save=save_with_race)])
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
        handled = await service.handle_pending_upload_response(response, sink, "repo", "!c", _reply_forbidden, _reply)
        assert handled is True

    asyncio.run(run())
    assert first_dest.read_text(encoding="utf-8") == "existing"
    assert (repo / "uploads" / "note_1.txt").read_text(encoding="utf-8") == "saved"
    assert "uploads/note_1.txt" in sink.sent[-1]


def test_upload_finalization_rejects_symlink_created_during_save(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    cfg.files.max_upload_mb = 1

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "uploads").mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    first_dest = repo / "uploads" / "note.txt"
    probe = repo / "uploads" / "probe-link"
    try:
        os.symlink(outside, probe)
        probe.unlink()
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    async def save_with_symlink_race(path: str) -> None:
        os.symlink(outside, first_dest)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("saved")

    request = _event_with_attachments([_attachment("note.txt", save=save_with_symlink_race)])
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
        handled = await service.handle_pending_upload_response(response, sink, "repo", "!c", _reply_forbidden, _reply)
        assert handled is True

    asyncio.run(run())
    assert "Upload failed: Upload destination is a symlink." in sink.sent[-1]
    assert outside.read_text(encoding="utf-8") == "outside"
    assert not (repo / "uploads" / "note_1.txt").exists()


class _FakeLogger:
    def info(self, name: str, extra=None):
        return None


def _reply_forbidden(sink: _FakeSink, msg: str):
    return sink.send(msg)


def _reply(sink: _FakeSink, msg: str):
    return sink.send(msg)
