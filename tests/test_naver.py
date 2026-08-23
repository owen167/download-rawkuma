import asyncio

from rawkuma_bot.config.settings import Settings
from rawkuma_bot.downloaders.models import Chapter
from rawkuma_bot.downloaders.naver.downloader import NaverDownloader


LIST_URL = "https://comic.naver.com/webtoon/list?titleId=807777"
DETAIL_URL = "https://comic.naver.com/webtoon/detail?titleId=807777&no=40"


LIST_HTML = """
<html><head>
<meta property="og:title" content="Demo Webtoon : 네이버 웹툰">
<meta property="og:image" content="https://image.naver.com/demo-cover.jpg">
<meta property="og:description" content="A public demo webtoon.">
</head><body>
<a href="/webtoon/detail?titleId=807777&no=39">Episode 39</a>
<a href="/webtoon/detail?titleId=807777&no=40">Episode 40</a>
</body></html>
"""


DETAIL_HTML = """
<html><head><title>Demo Webtoon Episode 40 : 네이버 웹툰</title></head><body>
<div class="detail_view">
  <img src="https://image.naver.com/episode/040/001.webp">
  <img data-src="https://image.naver.com/episode/040/002.jpg">
  <img src="https://comic.naver.com/static/logo.png">
</div>
</body></html>
"""


def make_downloader(tmp_path):
    return NaverDownloader(Settings(temp_dir=tmp_path / "temp", output_dir=tmp_path / "downloads"))


def test_naver_url_support_and_types():
    assert NaverDownloader.supports(LIST_URL)
    assert NaverDownloader.is_manga_url(LIST_URL)
    assert NaverDownloader.is_chapter_url(DETAIL_URL)
    assert not NaverDownloader.supports("https://example.com/webtoon/list?titleId=807777")
    assert not NaverDownloader.is_manga_url(DETAIL_URL)


def test_extracts_naver_info_and_chapters(tmp_path):
    downloader = make_downloader(tmp_path)

    async def fake_get_text(url, referer=None):
        return LIST_HTML

    downloader._get_text = fake_get_text
    info = asyncio.run(downloader.get_manga_info(LIST_URL))
    chapters = asyncio.run(downloader.get_chapters(LIST_URL))

    assert info.title == "Demo Webtoon"
    assert info.source == "Naver"
    assert info.cover_url.endswith("demo-cover.jpg")
    assert [chapter.number for chapter in chapters] == ["40", "39"]
    assert chapters[0].url == DETAIL_URL


def test_extracts_direct_chapter_and_ordered_images(tmp_path):
    downloader = make_downloader(tmp_path)

    async def fake_get_text(url, referer=None):
        return DETAIL_HTML

    downloader._get_text = fake_get_text
    chapter = asyncio.run(downloader.get_chapter(DETAIL_URL))
    images = asyncio.run(downloader.get_images(Chapter(chapter.number, chapter.title, DETAIL_URL)))

    assert chapter.number == "40"
    assert [image.number for image in images] == [1, 2]
    assert [image.extension for image in images] == [".webp", ".jpg"]
