from __future__ import annotations

import asyncio
import logging
import mimetypes
from pathlib import Path
from typing import Any

import aiohttp

from rawkuma_bot.config.settings import Settings

log = logging.getLogger(__name__)


class GoFileUploadError(RuntimeError):
    """Raised when GoFile rejects or cannot complete a chapter upload."""


class GoFileStorage:
    upload_endpoint = "https://upload.gofile.io/uploadfile"
    api_endpoint = "https://api.gofile.io"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.timeout = aiohttp.ClientTimeout(total=settings.request_timeout_seconds)
        self.account_token = settings.gofile_token or None

    @staticmethod
    def _check_payload(payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("status") != "ok":
            raise GoFileUploadError(f"GoFile returned {payload.get('status', 'unknown error')}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise GoFileUploadError("GoFile returned an invalid response")
        return data

    async def _upload_file(
        self,
        session: aiohttp.ClientSession,
        path: Path,
        folder_id: str | None,
        token: str | None,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.settings.retry_attempts + 1):
            try:
                form = aiohttp.FormData()
                with path.open("rb") as file_handle:
                    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    form.add_field("file", file_handle, filename=path.name, content_type=content_type)
                    if folder_id:
                        form.add_field("folderId", folder_id)
                    headers = {"Authorization": f"Bearer {token}"} if token else {}
                    async with session.post(self.upload_endpoint, data=form, headers=headers) as response:
                        payload = await response.json(content_type=None)
                return self._check_payload(payload)
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, GoFileUploadError) as exc:
                last_error = exc
                if attempt < self.settings.retry_attempts:
                    await asyncio.sleep(self.settings.retry_backoff_seconds * attempt)
        raise GoFileUploadError(f"GoFile upload failed for {path.name}") from last_error

    async def publish_file(self, path: Path, display_name: str) -> str:
        if not path.is_file():
            raise GoFileUploadError("Chapter archive does not exist")
        token = self.account_token
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            data = await self._upload_file(session, path, None, token)
        download_page = data.get("downloadPage")
        if isinstance(download_page, str) and download_page:
            log.info("GoFile archive upload completed file=%s", path.name)
            return download_page
        folder_code = data.get("parentFolderCode")
        if isinstance(folder_code, str) and folder_code:
            log.info("GoFile archive upload completed file=%s", path.name)
            return f"https://gofile.io/d/{folder_code}"
        raise GoFileUploadError("GoFile did not return a share link")
