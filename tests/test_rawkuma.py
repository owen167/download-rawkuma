from pathlib import Path

from rawkuma_bot.config.settings import Settings
from rawkuma_bot.downloaders.models import Chapter, MangaInfo
from rawkuma_bot.downloaders.rawkuma.downloader import RawkumaDownloader
from rawkuma_bot.services.archive import build_archive


SERIES_HTML = """
<h1 itemprop="name">Demo Manga</h1>
<img class="custom-logo" src="https://rawkuma.net/wp-content/uploads/2025/09/Rawkuma-Logo.png" alt="Rawkuma">
<img class="wp-post-image" src="/cover.webp" alt="Demo Manga">
<div id="chapter-list">
 <div data-chapter-number="2"><span>Chapter 2</span><a href="/manga/demo/chapter-2">read</a></div>
 <div data-chapter-number="1.5"><span>Chapter 1.5</span><a href="/manga/demo/chapter-1.5">read</a></div>
</div>
"""

CHAPTER_HTML = """
<div data-image-data><img src="https://cdn.example/002.webp"><img src="https://cdn.example/001.webp"></div>
"""


def test_supports_only_rawkuma() -> None:
    assert RawkumaDownloader.supports("https://rawkuma.net/manga/demo/")
    assert not RawkumaDownloader.supports("https://example.com/manga/demo/")


async def fake_series(url: str, referer: str | None = None) -> str:
    return SERIES_HTML


async def fake_chapter(url: str, referer: str | None = None) -> str:
    return CHAPTER_HTML


import pytest


@pytest.mark.asyncio
async def test_extracts_title_chapters_and_images(tmp_path: Path) -> None:
    downloader = RawkumaDownloader(Settings(temp_dir=tmp_path / "temp", output_dir=tmp_path / "out"))
    downloader._get_text = fake_series
    info = await downloader.get_manga_info("https://rawkuma.net/manga/demo/")
    chapters = await downloader.get_chapters(info.url)
    assert info.title == "Demo Manga"
    assert info.cover_url == "https://rawkuma.net/cover.webp"
    assert [chapter.number for chapter in chapters] == ["2", "1.5"]
    downloader._get_text = fake_chapter
    images = await downloader.get_images(chapters[0])
    assert [image.url for image in images] == ["https://cdn.example/002.webp", "https://cdn.example/001.webp"]
    assert images[0].extension == ".webp"


def test_archive_preserves_nested_layout(tmp_path: Path) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    (image_dir / "001.webp").write_bytes(b"one")
    (image_dir / "002.webp").write_bytes(b"two")
    archive = build_archive(MangaInfo("Demo Manga", "https://rawkuma.net/manga/demo/"), Chapter("10.354", "Chapter 10.354", "https://rawkuma.net/manga/demo/chapter-10.354"), image_dir, tmp_path / "out")
    import zipfile
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.namelist() == ["Demo Manga/Chapter_10.354/001.webp", "Demo Manga/Chapter_10.354/002.webp"]
