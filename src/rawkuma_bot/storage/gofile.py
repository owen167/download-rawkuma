from __future__ import annotations

import asyncio
import logging
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
                    form.add_field("file", file_handle, filename=path.name, content_type="image/webp")
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

    async def _rename_folder(self, session: aiohttp.ClientSession, folder_id: str, folder_name: str, token: str | None) -> None:
        if not token:
            return
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"attribute": "name", "attributeValue": folder_name}
        async with session.put(f"{self.api_endpoint}/contents/{folder_id}/update", json=payload, headers=headers) as response:
            result = await response.json(content_type=None)
        self._check_payload(result)

    async def publish_directory(self, directory: Path, display_name: str) -> str:
        files = sorted(path for path in directory.iterdir() if path.is_file())
        if not files:
            raise GoFileUploadError("Chapter has no image files")

        folder_id: str | None = None
        folder_code: str | None = None
        token = self.account_token
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            for index, path in enumerate(files):
                data = await self._upload_file(session, path, folder_id, token)
                if index == 0:
                    folder_id = data.get("parentFolder")
                    folder_code = data.get("parentFolderCode")
                    token = token or data.get("guestToken")
                    if folder_id:
                        await self._rename_folder(session, folder_id, display_name, token)
                log.info("GoFile upload completed file=%s position=%d total=%d", path.name, index + 1, len(files))

        if folder_code:
            return f"https://gofile.io/d/{folder_code}"
        download_page = data.get("downloadPage")
        if isinstance(download_page, str) and download_page:
            return download_page
        raise GoFileUploadError("GoFile did not return a share link")
