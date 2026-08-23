from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlparse, urlunparse

import aiohttp
from bs4 import BeautifulSoup

from rawkuma_bot.config.settings import Settings
from rawkuma_bot.downloaders.models import Chapter, ImageRef, MangaInfo, Progress
from rawkuma_bot.services.naver_image_merge import merge_naver_images
from .errors import (
    ChapterNotFound,
    DownloadFailed,
    ImagesNotFound,
    InvalidNaverURL,
    MangaNotFound,
    NaverError,
    NetworkError,
    SourceUnavailable,
)

log = logging.getLogger(__name__)


class NaverDownloader:
    source = "Naver"
    base_url = "https://comic.naver.com/"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.timeout = aiohttp.ClientTimeout(total=settings.request_timeout_seconds)
        self.headers = {
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        }

    @staticmethod
    def supports(url: str) -> bool:
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        host = parsed.netloc.lower().split(":", 1)[0]
        return host in {"comic.naver.com", "m.comic.naver.com"} and parsed.path.startswith("/webtoon/")

    @staticmethod
    def is_manga_url(url: str) -> bool:
        return NaverDownloader.supports(url) and urlparse(url).path.rstrip("/").endswith("/list")

    @staticmethod
    def is_chapter_url(url: str) -> bool:
        return NaverDownloader.supports(url) and urlparse(url).path.rstrip("/").endswith("/detail") and bool(
            parse_qs(urlparse(url).query).get("no")
        )

    @staticmethod
    def _mobile_url(url: str, page: int | None = None) -> str:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if page is not None:
            query["page"] = str(page)
        return urlunparse(parsed._replace(netloc="m.comic.naver.com", query=urlencode(query)))

    async def _get_text(self, url: str, referer: str | None = None) -> str:
        if not self.supports(url):
            raise InvalidNaverURL("Invalid Naver URL")
        request_url = self._mobile_url(url)
        headers = dict(self.headers)
        if referer:
            headers["Referer"] = referer
        try:
            async with aiohttp.ClientSession(timeout=self.timeout, headers=headers) as session:
                async with session.get(request_url, allow_redirects=True) as response:
                    if response.status in {403, 404}:
                        raise SourceUnavailable(f"Naver returned HTTP {response.status}")
                    if response.status >= 500:
                        raise NetworkError(f"Naver returned HTTP {response.status}")
                    if response.status != 200:
                        raise NetworkError(f"Naver returned HTTP {response.status}")
                    return await response.text(errors="replace")
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise NetworkError("Network Error") from exc

    @staticmethod
    def _soup(raw_html: str) -> BeautifulSoup:
        return BeautifulSoup(raw_html, "html.parser")

    @staticmethod
    def _clean(text: str | None) -> str:
        return " ".join((text or "").split()).strip()

    @staticmethod
    def _title_from_soup(soup: BeautifulSoup) -> str:
        node = soup.select_one("meta[property='og:title']")
        title = node.get("content") if node else ""
        if not title:
            heading = soup.select_one("h1, .comicinfo h2, .section_info h2")
            title = heading.get_text(" ", strip=True) if heading else ""
        if not title and soup.title:
            title = soup.title.get_text(" ", strip=True)
        title = NaverDownloader._clean(title)
        title = re.sub(r"\s*[:|\-]\s*(?:네이버\s*웹툰|Naver\s*Webtoon)\s*$", "", title, flags=re.I)
        return title or "Naver Webtoon"

    @staticmethod
    def _image_value(node) -> str | None:
        if node is None:
            return None
        if node.name == "meta":
            value = node.get("content")
            return value if value and not value.startswith("data:image") else None
        for attribute in ("data-src", "data-lazy-src", "data-original", "src"):
            value = node.get(attribute)
            if value and not value.startswith("data:image"):
                return value
        return None

    async def get_manga_info(self, url: str) -> MangaInfo:
        raw_html = await self._get_text(url)
        soup = self._soup(raw_html)
        title = self._title_from_soup(soup)
        if not title or title == "Naver Webtoon":
            raise MangaNotFound("Naver manga was not found")
        cover = self._image_value(soup.select_one("meta[property='og:image']"))
        if not cover:
            cover = self._image_value(soup.select_one(".comicinfo img, .section_info img, img[alt]"))
        description_node = soup.select_one("meta[property='og:description']")
        description = description_node.get("content") if description_node else None
        return MangaInfo(
            title=title,
            url=url,
            source=self.source,
            cover_url=urljoin(url, cover) if cover else None,
            status="Available",
            description=self._clean(description),
        )

    @staticmethod
    def _chapter_no(url: str) -> str | None:
        values = parse_qs(urlparse(url).query).get("no", [])
        return values[0] if values and values[0].isdigit() else None

    async def get_chapters(self, url: str) -> list[Chapter]:
        if not self.is_manga_url(url):
            raise InvalidNaverURL("Use a Naver webtoon list URL")
        raw_html = await self._get_text(url)
        first_soup = self._soup(raw_html)
        total_node = first_soup.select_one(".current_pg .total")
        try:
            total_pages = max(1, int(total_node.get_text(strip=True))) if total_node else 1
        except ValueError:
            total_pages = 1
        chapters: list[Chapter] = []
        seen: set[str] = set()
        for page in range(1, total_pages + 1):
            page_soup = first_soup if page == 1 else self._soup(await self._get_text(self._mobile_url(url, page=page)))
            for anchor in page_soup.select("a[href*='/webtoon/detail']"):
                chapter_url = urljoin(url, anchor.get("href", ""))
                number = self._chapter_no(chapter_url)
                if not number or chapter_url in seen:
                    continue
                seen.add(chapter_url)
                visible_title = self._clean(anchor.get_text(" ", strip=True))
                chapters.append(Chapter(number=number, title=visible_title or f"Chapter {number}", url=chapter_url))
        chapters.sort(key=lambda chapter: chapter.sort_key, reverse=True)
        if not chapters:
            raise ChapterNotFound("Naver chapters were not found")
        return chapters

    async def get_chapter(self, url: str) -> Chapter:
        if not self.is_chapter_url(url):
            raise InvalidNaverURL("Invalid Naver chapter URL")
        raw_html = await self._get_text(url, referer=self.base_url)
        soup = self._soup(raw_html)
        number = self._chapter_no(url)
        if soup.title:
            match = re.search(r"(?:Episode|Chapter|회)\s*(\d+)", soup.title.get_text(" ", strip=True), re.I)
            if match:
                number = match.group(1)
        if not number:
            raise ChapterNotFound("Naver chapter number was not found")
        title = f"Chapter {number}"
        for node in soup.select("h1, h2, .sub_title, .section_info"):
            text = self._clean(node.get_text(" ", strip=True))
            if text:
                title = text[:200]
                break
        return Chapter(number=number, title=title, url=url)

    async def get_images(self, chapter: Chapter) -> list[ImageRef]:
        raw_html = await self._get_text(chapter.url, referer=self.base_url)
        soup = self._soup(raw_html)
        selectors = (
            "img.toon_image",
            "div.detail_view img",
            "div.wt_viewer img",
            "div.comic_viewer img",
            "div[class*='viewer'] img",
            "body > div:nth-of-type(1) > div:nth-of-type(3) > div:nth-of-type(1) img",
        )
        nodes = []
        for selector in selectors:
            nodes = soup.select(selector)
            if nodes:
                break
        if not nodes:
            nodes = soup.select("img")
        urls: list[str] = []
        seen: set[str] = set()
        for node in nodes:
            value = self._image_value(node)
            if not value:
                continue
            absolute = urljoin(chapter.url, value)
            lowered = absolute.lower()
            if absolute.startswith("http") and absolute not in seen and not any(
                marker in lowered for marker in ("logo", "icon", "profile", "thumbnail")
            ):
                urls.append(absolute)
                seen.add(absolute)
        if not urls:
            raise ImagesNotFound("Naver chapter images were not found")
        return [ImageRef(number=index, url=value, extension=self._extension(value)) for index, value in enumerate(urls, 1)]

    @staticmethod
    def _extension(url: str) -> str:
        suffix = Path(urlparse(url).path).suffix.lower()
        return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"} else ".jpg"

    async def download_chapter(
        self,
        chapter: Chapter,
        destination: Path,
        progress: Progress,
        on_progress: Callable[[], Awaitable[None]] | None = None,
    ) -> list[Path]:
        images = await self.get_images(chapter)
        progress.total = len(images)
        if on_progress:
            await on_progress()
        destination.mkdir(parents=True, exist_ok=True)
        semaphore = asyncio.Semaphore(self.settings.max_concurrent_pages)
        downloaded: list[Path | None] = [None] * len(images)

        async def download_one(index: int, image: ImageRef) -> None:
            async with semaphore:
                target = destination / f"{image.number:03d}{image.extension}"
                last_error: Exception | None = None
                for attempt in range(1, self.settings.retry_attempts + 1):
                    try:
                        headers = dict(self.headers)
                        headers["Referer"] = chapter.url
                        async with aiohttp.ClientSession(timeout=self.timeout, headers=headers) as session:
                            async with session.get(image.url) as response:
                                if response.status != 200:
                                    raise NetworkError(f"HTTP {response.status}")
                                with target.open("wb") as output:
                                    async for chunk in response.content.iter_chunked(64 * 1024):
                                        output.write(chunk)
                                        progress.bytes_downloaded += len(chunk)
                        if target.stat().st_size == 0:
                            raise DownloadFailed("empty image")
                        downloaded[index] = target
                        progress.current += 1
                        progress.update_speed()
                        if on_progress:
                            await on_progress()
                        return
                    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, NaverError) as exc:
                        last_error = exc
                        target.unlink(missing_ok=True)
                        if attempt < self.settings.retry_attempts:
                            await asyncio.sleep(self.settings.retry_backoff_seconds * attempt)
                raise DownloadFailed(f"page {image.number} failed after {self.settings.retry_attempts} attempts") from last_error

        try:
            await asyncio.gather(*(download_one(index, image) for index, image in enumerate(images)))
            source_paths = [path for path in downloaded if path is not None]
            merged_dir = destination / ".merged"
            merged_paths = merge_naver_images(source_paths, merged_dir)
            for path in source_paths:
                path.unlink(missing_ok=True)
            renamed_paths: list[Path] = []
            for index, path in enumerate(merged_paths, 1):
                target = destination / f"{index:03d}{path.suffix.lower()}"
                path.replace(target)
                renamed_paths.append(target)
            shutil.rmtree(merged_dir, ignore_errors=True)
            return renamed_paths
        except Exception:
            for path in downloaded:
                if path:
                    path.unlink(missing_ok=True)
            shutil.rmtree(destination / ".merged", ignore_errors=True)
            raise
