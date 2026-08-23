import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from PIL import Image

from rawkuma_bot.config.settings import Settings
from rawkuma_bot.downloaders.kakao_page.downloader import KakaoPageDownloader
from rawkuma_bot.downloaders.kakao_page.errors import ProductNotReadable
from rawkuma_bot.downloaders.models import Chapter, Progress


def make_downloader(tmp_path: Path) -> KakaoPageDownloader:
    return KakaoPageDownloader(Settings(temp_dir=tmp_path / "temp", output_dir=tmp_path / "output"))


def test_kakao_page_url_classification(tmp_path):
    downloader = make_downloader(tmp_path)
    work = "https://page.kakao.com/home/demo-title/58200560/"
    chapter = "https://page.kakao.com/content/58200560/viewer/58202217/"
    assert downloader.supports(work)
    assert downloader.is_manga_url(work)
    assert downloader.supports(chapter)
    assert downloader.is_chapter_url(chapter)
    assert not downloader.is_manga_url(chapter)
    assert not downloader.supports("https://webtoon.kakao.com/content/demo/1776")


def test_kakao_page_listing_keeps_only_free_products(tmp_path):
    downloader = make_downloader(tmp_path)
    downloader._get_json = AsyncMock(side_effect=[
        {"result": {"list": [
            {"cursor_index": 1, "item": {"product_id": 10, "title": "Demo 1화", "is_free": True}},
            {"cursor_index": 2, "item": {"product_id": 11, "title": "Demo 2화", "is_free": False}},
        ], "has_next": False}},
    ])
    chapters = asyncio.run(downloader.get_chapters("https://page.kakao.com/home/demo/58200560"))
    assert chapters == [Chapter("1", "Demo 1화", "https://page.kakao.com/content/58200560/viewer/10/")]


def test_kakao_page_download_builds_html_and_public_image(tmp_path):
    downloader = make_downloader(tmp_path)
    downloader._viewer_data = AsyncMock(return_value={
        "item": {"title": "Demo 1화", "is_free": True},
        "viewer_data": {"ats_server_url": "https://dn-img-page.kakao.com/sdownload/resource?kid=", "contents_list": [{"secure_url": "signed.json"}]},
    })
    downloader._get_signed_json = AsyncMock(return_value={"contentInfo": {"paragraphList": [
        {"type": "DIV", "text": "Hello", "childParagraphList": [
            {"type": "IMG", "image": {"imageSrcKey": "public-key-1", "imageFilename": "page-1.jpg"}},
            {"type": "IMG", "image": {"imageSrcKey": "public-key-2", "imageFilename": "page-2.jpg"}},
        ]}
    ]}})

    async def fake_asset(url, target, referer):
        height = 9000 if target.name == "001.jpg" else 9000
        Image.new("RGB", (2, height), (255, 255, 255)).save(target, format="JPEG")

    downloader._download_asset = fake_asset
    destination = tmp_path / "chapter"
    files = asyncio.run(downloader.download_chapter(
        Chapter("1", "Demo 1화", "https://page.kakao.com/content/58200560/viewer/10/"),
        destination,
        Progress(),
    ))
    assert [path.name for path in files] == ["chapter.html", "001.jpg", "002.jpg"]
    with Image.open(destination / "images" / "001.jpg") as image:
        assert image.size == (2, 14000)
    with Image.open(destination / "images" / "002.jpg") as image:
        assert image.size == (2, 4000)
    assert "Hello" in (destination / "chapter.html").read_text(encoding="utf-8")
    assert 'images/001.jpg' in (destination / "chapter.html").read_text(encoding="utf-8")
    assert 'images/002.jpg' in (destination / "chapter.html").read_text(encoding="utf-8")


def test_kakao_page_unfree_product_is_rejected(tmp_path):
    downloader = make_downloader(tmp_path)
    downloader._viewer_data = AsyncMock(return_value={"item": {"title": "Paid", "is_free": False}})
    try:
        asyncio.run(downloader.get_chapter("https://page.kakao.com/content/58200560/viewer/10/"))
    except ProductNotReadable:
        return
    raise AssertionError("unfree Kakao Page product was not rejected")
