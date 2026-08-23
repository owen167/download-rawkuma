import base64
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from rawkuma_bot.config.settings import Settings
from rawkuma_bot.downloaders.kakao.downloader import KakaoDownloader
from rawkuma_bot.downloaders.kakao.errors import EpisodeNotReadable
from rawkuma_bot.downloaders.models import Chapter


def make_downloader(tmp_path: Path) -> KakaoDownloader:
    return KakaoDownloader(Settings(temp_dir=tmp_path / "temp", output_dir=tmp_path / "output"))


def test_kakao_url_classification(tmp_path):
    downloader = make_downloader(tmp_path)
    content_url = "https://webtoon.kakao.com/content/하렘생존기/1776"
    viewer_url = "https://webtoon.kakao.com/viewer/하렘생존기-001/74570"
    assert downloader.supports(content_url)
    assert downloader.is_manga_url(content_url)
    assert not downloader.is_chapter_url(content_url)
    assert downloader.supports(viewer_url)
    assert downloader.is_chapter_url(viewer_url)
    assert not downloader.is_manga_url(viewer_url)
    assert not downloader.supports("https://example.com/content/demo/1776")


def test_kakao_cover_url_adds_cdn_webp_suffix(tmp_path):
    downloader = make_downloader(tmp_path)
    raw = "https://kr-a.kakaopagecdn.com/P/C/1776/sharing/2x/cover-id"
    assert downloader._cover_url({"thumbnailImage": raw}) == raw + ".webp"
    ready = raw + ".webp"
    assert downloader._cover_url({"thumbnailImage": ready}) == ready


def test_kakao_chapter_number_uses_visible_title(tmp_path):
    assert KakaoDownloader._chapter_number({"title": "0화", "no": 1}) == "0"
    assert KakaoDownloader._chapter_number({"title": "12화 특별편", "no": 13}) == "12"
    assert KakaoDownloader._chapter_number({"title": "무료 공개", "no": 13}) == "13"


def test_kakao_data_url_detects_webp_magic_bytes():
    payload = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"data"
    data_url = "data:text/plain;base64," + base64.b64encode(payload).decode()
    data, extension = KakaoDownloader._data_url_bytes(data_url)
    assert data == payload
    assert extension == ".webp"


def test_kakao_episode_listing_uses_public_v2_endpoint(tmp_path):
    downloader = make_downloader(tmp_path)
    downloader._api_json = AsyncMock(
        side_effect=[
            {"data": {"episodes": [
                {"id": 10, "seoId": "demo-001", "no": 1, "title": "0화", "readable": True},
                {"id": 11, "seoId": "demo-002", "no": 2, "title": "1화", "readable": False},
            ]}},
        ]
    )
    chapters = asyncio.run(downloader.get_chapters("https://webtoon.kakao.com/content/demo/1776"))
    assert len(chapters) == 1
    assert chapters[0] == Chapter("0", "0화", "https://webtoon.kakao.com/viewer/demo-001/10")


def test_kakao_unreadable_episode_is_rejected(tmp_path):
    downloader = make_downloader(tmp_path)
    downloader._episode_media = AsyncMock(return_value={"episode": {"readable": False, "title": "1화", "no": 2}})
    try:
        asyncio.run(downloader.get_chapter("https://webtoon.kakao.com/viewer/demo-001/10"))
    except EpisodeNotReadable:
        return
    raise AssertionError("unreadable Kakao episode was not rejected")
