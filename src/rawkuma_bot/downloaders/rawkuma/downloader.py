from __future__ import annotations

import asyncio
import html as html_lib
import logging
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from rawkuma_bot.config.settings import Settings
from rawkuma_bot.downloaders.models import Chapter, ImageRef, MangaInfo, Progress
from .errors import (
    ChapterNotFound,
    DownloadFailed,
    ImagesNotFound,
    InvalidRawkumaURL,
    MangaNotFound,
    NetworkError,
    SourceUnavailable,
)

log = logging.getLogger(__name__)
CHAPTER_NUMBER_RE = re.compile(r"(?i)\b(?:chapter|chapitre|cap[ií]tulo|ch|c)\.?\s*(\d+(?:\.\d+)?)")
URL_CHAPTER_RE = re.compile(r"(?i)(?:chapter|chap)[-_]?(\d+(?:\.\d+)?)")


class RawkumaDownloader:
    source = "Rawkuma"
    base_url = "https://rawkuma.net/"

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
        return parsed.scheme in {"http", "https"} and parsed.netloc.lower().endswith("rawkuma.net")

    async def _get_text(self, url: str, referer: str | None = None) -> str:
        if not self.supports(url):
            raise InvalidRawkumaURL("Invalid Rawkuma URL")
        headers = dict(self.headers)
        if referer:
            headers["Referer"] = referer
        try:
            async with aiohttp.ClientSession(timeout=self.timeout, headers=headers) as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status in {403, 404}:
                        raise SourceUnavailable(f"Rawkuma returned HTTP {response.status}")
                    if response.status >= 500:
                        raise NetworkError(f"Rawkuma returned HTTP {response.status}")
                    if response.status != 200:
                        raise NetworkError(f"Rawkuma returned HTTP {response.status}")
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
    def _chapter_number(text: str, url: str = "") -> str | None:
        match = CHAPTER_NUMBER_RE.search(text)
        if not match:
            match = URL_CHAPTER_RE.search(url)
        if not match:
            return None
        return match.group(1)

    @staticmethod
    def _absolute(base: str, value: str | None) -> str:
        return urljoin(base, (value or "").strip())

    async def get_manga_info(self, url: str) -> MangaInfo:
        raw_html = await self._get_text(url)
        soup = self._soup(raw_html)
        title_node = soup.select_one('h1[itemprop="name"]') or soup.select_one("meta[property='og:title']")
        if title_node and title_node.name == "meta":
            title = self._clean(title_node.get("content"))
        else:
            title = self._clean(title_node.get_text(" ", strip=True) if title_node else "")
        if not title:
            title = self._clean((soup.title.get_text(" ", strip=True) if soup.title else ""))
        if not title:
            raise MangaNotFound("Manga Not Found")
        def image_value(node) -> str | None:
            if node is None:
                return None
            if node.name == "meta":
                return node.get("content")
            for attribute in ("src", "data-src", "data-lazy-src", "data-original"):
                value = node.get(attribute)
                if value and not value.startswith("data:image"):
                    return value
            return None

        def is_brand_asset(value: str | None) -> bool:
            lowered = (value or "").lower()
            return any(marker in lowered for marker in ("rawkuma-logo", "/logo", "upvote", "funny", "surprised", "angry", "sad"))

        cover = image_value(soup.select_one("meta[property='og:image']"))
        if is_brand_asset(cover):
            cover = None
        if not cover:
            image_candidates = soup.select("img.wp-post-image, img[itemprop='image'], img[alt]")
            for candidate in image_candidates:
                value = image_value(candidate)
                alt = self._clean(candidate.get("alt"))
                classes = set(candidate.get("class", []))
                if value and not is_brand_asset(value) and ("wp-post-image" in classes or alt.lower() == title.lower()):
                    cover = value
                    break
        if not cover:
            for candidate in soup.select("img"):
                value = image_value(candidate)
                if value and not is_brand_asset(value):
                    cover = value
                    break
        status_node = soup.select_one('[itemprop="status"]') or soup.select_one(".post-content_item .summary-content")
        description_node = soup.select_one('[itemprop="description"]') or soup.select_one(".summary_content")
        return MangaInfo(
            title=title,
            url=url,
            cover_url=self._absolute(url, cover) if cover else None,
            status=self._clean(status_node.get_text(" ", strip=True) if status_node else None),
            description=self._clean(description_node.get_text(" ", strip=True) if description_node else None),
        )

    async def get_chapters(self, url: str) -> list[Chapter]:
        raw_html = await self._get_text(url)
        soup = self._soup(raw_html)
        rows = soup.select("#chapter-list [data-chapter-number]")
        if not rows:
            rows = [node for node in soup.select("a[href]") if "/chapter" in (node.get("href") or "").lower()]
        chapters: list[Chapter] = []
        seen: set[tuple[float, str]] = set()
        for row in rows:
            href_node = row.select_one("a[href]")
            if href_node is None and row.name == "a":
                href_node = row
            href = href_node.get("href") if href_node else None
            chapter_url = self._absolute(url, href)
            text = self._clean(row.get_text(" ", strip=True))
            # Rawkuma may put an internal record ID in data-chapter-number or the URL.
            # The visible row text is authoritative for the chapter label shown to readers.
            number = self._chapter_number(text)
            if number is None:
                number = self._chapter_number(row.get("data-chapter-number") or "")
            if number is None:
                number = self._chapter_number("", chapter_url)
            if number is None or not chapter_url.startswith("http"):
                continue
            key = (number, chapter_url)
            if key in seen:
                continue
            seen.add(key)
            chapters.append(Chapter(number=number, title=f"Chapter {number}", url=chapter_url))
        chapters.sort(key=lambda chapter: chapter.sort_key, reverse=True)
        if not chapters:
            raise ChapterNotFound("Chapter Not Found")
        return chapters

    async def get_chapter(self, url: str, number: str | None = None) -> Chapter:
        if not self.supports(url):
            raise InvalidRawkumaURL("Invalid Rawkuma URL")
        if number is None:
            raw_html = await self._get_text(url, referer=self.base_url)
            soup = self._soup(raw_html)
            title_text = self._clean(soup.title.get_text(" ", strip=True) if soup.title else "")
            number = self._chapter_number(title_text)
            if number is None:
                for node in soup.select("h1, h2, [data-chapter-number]"):
                    number = self._chapter_number(self._clean(node.get_text(" ", strip=True)))
                    if number is not None:
                        break
            if number is None:
                number = self._chapter_number("", url)
        if number is None:
            raise ChapterNotFound("Chapter Not Found")
        return Chapter(number=number, title=f"Chapter {number}", url=url)

    @staticmethod
    def _extract_image_urls(raw_html: str, soup: BeautifulSoup, page_url: str) -> list[str]:
        urls: list[str] = []
        script_match = re.search(r"var\s+chapImages\s*=\s*'([^']+)'", raw_html)
        if script_match:
            urls.extend(part.strip() for part in script_match.group(1).split(","))
        if not urls:
            for image in soup.select("[data-image-data] img"):
                for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                    value = image.get(attr)
                    if value and not value.startswith("data:image"):
                        urls.append(value)
                        break
        if not urls:
            for image in soup.select("[data-image-data]"):
                raw_data = html_lib.unescape(image.get("data-image-data", ""))
                for match in re.findall(r"https?://[^\"'\\\s]+", raw_data):
                    urls.append(match.replace("\\/", "/"))
        if not urls:
            for image in soup.select("img"):
                for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                    value = image.get(attr)
                    if value and not value.startswith("data:image"):
                        urls.append(value)
                        break
        normalized: list[str] = []
        seen: set[str] = set()
        for value in urls:
            absolute = urljoin(page_url, value.strip())
            if absolute.startswith("http") and absolute not in seen:
                normalized.append(absolute)
                seen.add(absolute)
        return normalized

    async def get_images(self, chapter: Chapter) -> list[ImageRef]:
        raw_html = await self._get_text(chapter.url, referer=self.base_url)
        soup = self._soup(raw_html)
        urls = self._extract_image_urls(raw_html, soup, chapter.url)
        if not urls:
            raise ImagesNotFound("Images Not Found")
        return [ImageRef(number=index, url=image_url, extension=self._extension(image_url)) for index, image_url in enumerate(urls, 1)]

    @staticmethod
    def _extension(url: str) -> str:
        suffix = Path(urlparse(url).path).suffix.lower()
        return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"} else ".jpg"

    async def download_chapter(self, chapter: Chapter, destination: Path, progress: Progress) -> list[Path]:
        images = await self.get_images(chapter)
        progress.total = len(images)
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
                        return
                    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, RawkumaError) as exc:
                        last_error = exc
                        target.unlink(missing_ok=True)
                        if attempt < self.settings.retry_attempts:
                            await asyncio.sleep(self.settings.retry_backoff_seconds * attempt)
                raise DownloadFailed(f"page {image.number} failed after {self.settings.retry_attempts} attempts") from last_error

        try:
            await asyncio.gather(*(download_one(index, image) for index, image in enumerate(images)))
        except Exception:
            for path in downloaded:
                if path:
                    path.unlink(missing_ok=True)
            raise
        return [path for path in downloaded if path is not None]
