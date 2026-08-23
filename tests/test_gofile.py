from pathlib import Path

import pytest

from rawkuma_bot.config.settings import Settings
from rawkuma_bot.storage.gofile import GoFileStorage


@pytest.mark.asyncio
async def test_gofile_publish_directory_returns_folder_page(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "001.webp"
    second = tmp_path / "002.webp"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    storage = GoFileStorage(Settings(temp_dir=tmp_path / "temp", output_dir=tmp_path / "out"))
    uploaded: list[str] = []

    async def fake_upload(session, path, folder_id, token):
        uploaded.append(path.name)
        if len(uploaded) == 1:
            return {"parentFolder": "folder-id", "parentFolderCode": "share-code", "guestToken": "guest-token"}
        return {"parentFolder": "folder-id"}

    async def fake_rename(session, folder_id, folder_name, token):
        assert folder_id == "folder-id"
        assert folder_name == "Chapter_29"

    monkeypatch.setattr(storage, "_upload_file", fake_upload)
    monkeypatch.setattr(storage, "_rename_folder", fake_rename)

    link = await storage.publish_directory(tmp_path, "Chapter_29")

    assert link == "https://gofile.io/d/share-code"
    assert uploaded == ["001.webp", "002.webp"]


def test_gofile_rejects_error_envelope() -> None:
    with pytest.raises(Exception, match="error-rateLimit"):
        GoFileStorage._check_payload({"status": "error-rateLimit"})
