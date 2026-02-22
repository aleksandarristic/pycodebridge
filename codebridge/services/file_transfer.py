"""File upload/download handling for adapters."""

from __future__ import annotations

import os
import time
from typing import Awaitable, Callable, Dict

from .. import config as cfgmod
from ..routing.helpers import PendingUpload, UPLOAD_TTL_SECONDS
from ..transport import MessageEvent, ResponseSink
from ..util import path as pathutil


class FileTransferService:
    """Manage upload/download flows across transports."""

    def __init__(self, cfg: cfgmod.Config, logger) -> None:
        self.cfg = cfg
        self.logger = logger
        self._pending_uploads: Dict[str, PendingUpload] = {}

    async def handle_download(
        self,
        sink: ResponseSink,
        repo_path: str,
        rel_path: str,
        reply_forbidden: Callable[[ResponseSink, str], Awaitable[None]],
    ) -> None:
        if not sink.capabilities().downloads:
            await reply_forbidden(sink, "Downloads are not supported for this transport.")
            return
        if not rel_path:
            await reply_forbidden(sink, "Usage: !c download <path>")
            return
        try:
            target = pathutil.resolve_repo_file_path(repo_path, rel_path)
        except Exception as exc:
            await reply_forbidden(sink, f"Invalid path: {exc}")
            return
        if os.path.isdir(target):
            await reply_forbidden(sink, "Path is a directory; provide a file path.")
            return
        if not os.path.exists(target):
            await reply_forbidden(sink, "File not found.")
            return
        filename = os.path.basename(target)
        await sink.send_file(target, filename)

    async def handle_upload_request(
        self,
        event: MessageEvent,
        sink: ResponseSink,
        repo_name: str,
        repo_path: str,
        reply_forbidden: Callable[[ResponseSink, str], Awaitable[None]],
        reply: Callable[[ResponseSink, str], Awaitable[None]],
    ) -> None:
        if not sink.capabilities().uploads:
            await reply_forbidden(sink, "Uploads are not supported for this transport.")
            return
        max_bytes = self.cfg.files.max_upload_mb * 1024 * 1024
        too_large = [att.filename for att in event.attachments if att.size > max_bytes]
        if too_large:
            await reply_forbidden(sink, f"Files too large (max {self.cfg.files.max_upload_mb}MB): {', '.join(too_large)}")
            return
        upload = PendingUpload(
            repo_name=repo_name,
            repo_path=repo_path,
            attachments=event.attachments,
            user_id=event.author_id,
            created_at=time.time(),
            expires_at=time.time() + UPLOAD_TTL_SECONDS,
        )
        self._set_pending_upload(event, upload)
        suggestions = self._suggest_upload_paths(repo_path)
        hint = ", ".join(suggestions) if suggestions else "repo root"
        await reply(sink, f"Where do you want to put these file(s)? Reply with a relative path. Suggestions: {hint}")

    async def handle_pending_upload_response(
        self,
        event: MessageEvent,
        sink: ResponseSink,
        repo_name: str,
        prefix: str,
        reply_forbidden: Callable[[ResponseSink, str], Awaitable[None]],
        reply: Callable[[ResponseSink, str], Awaitable[None]],
        content_override: str | None = None,
    ) -> bool:
        content = (event.content if content_override is None else content_override) or ""
        if not content:
            return False
        upload = self._get_pending_upload(event)
        if not upload:
            return False
        if content.strip().startswith(prefix):
            return False
        rel_path = content.strip()
        try:
            target_path = pathutil.resolve_repo_file_path(upload.repo_path, rel_path)
        except Exception as exc:
            await reply_forbidden(sink, f"Invalid path: {exc}")
            return True
        is_dir = rel_path.endswith(("/", "\\")) or os.path.isdir(target_path)
        if len(upload.attachments) > 1 and not is_dir:
            await reply_forbidden(sink, "Provide a directory path when uploading multiple files.")
            return True
        saved = []
        for att in upload.attachments:
            dest = target_path
            if is_dir:
                dest = os.path.join(target_path, att.filename)
            dest = self._unique_path(dest)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            await att.save(dest)
            saved.append(os.path.relpath(dest, upload.repo_path))
        self._pop_pending_upload(event)
        await reply(sink, f"Saved {len(saved)} file(s):\n" + "\n".join(saved))
        self.logger.info(
            "upload.saved",
            extra={
                "platform": event.platform,
                "channel_id": event.channel_id,
                "user_id": event.author_id,
                "repo": upload.repo_name,
                "count": len(saved),
            },
        )
        return True

    def _upload_key(self, event: MessageEvent) -> str:
        return f"{event.platform}:{event.channel_id}:{event.author_id}"

    def has_pending_upload(self, event: MessageEvent) -> bool:
        """Return whether an unexpired upload prompt is waiting for a path reply."""
        return self._get_pending_upload(event) is not None

    def _set_pending_upload(self, event: MessageEvent, upload: PendingUpload) -> None:
        self._pending_uploads[self._upload_key(event)] = upload

    def _pop_pending_upload(self, event: MessageEvent) -> None:
        self._pending_uploads.pop(self._upload_key(event), None)

    def _get_pending_upload(self, event: MessageEvent) -> PendingUpload | None:
        upload = self._pending_uploads.get(self._upload_key(event))
        if not upload:
            return None
        if upload.expires_at < time.time():
            self._pending_uploads.pop(self._upload_key(event), None)
            return None
        return upload

    def _unique_path(self, path: str) -> str:
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        idx = 1
        while True:
            candidate = f"{base}_{idx}{ext}"
            if not os.path.exists(candidate):
                return candidate
            idx += 1

    def _suggest_upload_paths(self, repo_path: str) -> list[str]:
        suggestions = []
        try:
            for name in sorted(os.listdir(repo_path)):
                if name.startswith("."):
                    continue
                if name in {".git", "node_modules", "vendor"}:
                    continue
                full = os.path.join(repo_path, name)
                if os.path.isdir(full):
                    suggestions.append(f"{name}/")
                if len(suggestions) >= 5:
                    break
        except Exception:
            return []
        return suggestions
