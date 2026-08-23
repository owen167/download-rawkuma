from pathlib import Path

import aiohttp
import pytest

from rawkuma_bot.config.settings import Settings
from rawkuma_bot.storage.gofile import GoFileStorage


@pytest.mark.asyncio
async def test_gofile_publish_file_returns_download_page(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "Chapter_29.zip"
    archive.write_bytes(b"zip-data")
    storage = GoFileStorage(Settings(temp_dir=tmp_path / "temp", output_dir=tmp_path / "out"))
    uploaded: list[tuple[str, str | None]] = []

    async def fake_upload(session, path, folder_id, token):
        uploaded.append((path.name, token))
        return {"downloadPage": "https://gofile.io/d/share-code"}

    monkeypatch.setattr(storage, "_upload_file", fake_upload)

    link = await storage.publish_file(archive, archive.name)

    assert link == "https://gofile.io/d/share-code"
    assert uploaded == [("Chapter_29.zip", None)]


@pytest.mark.asyncio
async def test_gofile_retries_with_a_fresh_session_after_connection_error(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "Chapter_2.zip"
    archive.write_bytes(b"zip-data")
    storage = GoFileStorage(
        Settings(
            temp_dir=tmp_path / "temp",
            output_dir=tmp_path / "out",
            retry_attempts=2,
            retry_backoff_seconds=0.001,
        )
    )
    sessions: list[int] = []

    async def flaky_upload(session, path, folder_id, token):
        sessions.append(id(session))
        if len(sessions) == 1:
            raise aiohttp.ClientOSError("broken pipe")
        return {"downloadPage": "https://gofile.io/d/recovered"}

    monkeypatch.setattr(storage, "_upload_file", flaky_upload)
    link = await storage.publish_file(archive, archive.name)
    assert link == "https://gofile.io/d/recovered"
    assert len(sessions) == 2
    assert sessions[0] != sessions[1]


def test_gofile_rejects_error_envelope() -> None:
    with pytest.raises(Exception, match="error-rateLimit"):
        GoFileStorage._check_payload({"status": "error-rateLimit"})
