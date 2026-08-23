from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import random
import re
import shutil
import time
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import aiohttp
from playwright.async_api import Browser, BrowserContext, Page, Playwright, TimeoutError as PlaywrightTimeoutError, async_playwright

from rawkuma_bot.config.settings import Settings
from rawkuma_bot.downloaders.models import Chapter, ImageRef, MangaInfo, Progress
from rawkuma_bot.services.naver_image_merge import merge_naver_images
from rawkuma_bot.downloaders.kakao.errors import (
    ChapterNotFound,
    DownloadFailed,
    EpisodeNotReadable,
    ImagesNotFound,
    InvalidKakaoURL,
    KakaoError,
    MangaNotFound,
    NetworkError,
    SourceUnavailable,
)

log = logging.getLogger(__name__)


class KakaoDownloader:
    """Kakao Webtoon downloader limited to episodes Kakao exposes as readable."""

    CONTENT_HOSTS = {"webtoon.kakao.com", "page.kakao.com"}
    CONTENT_RE = re.compile(r"/content/[^/?#]+/(\d+)(?:[/?#]|$)")
    VIEWER_RE = re.compile(r"/viewer/([^/?#]+)/?(\d+)(?:[/?#]|$)")
    API_ROOT = "https://gateway-kw.kakao.com"
    VIEWER_ROOT = "https://webtoon.kakao.com/viewer"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._http_session: aiohttp.ClientSession | None = None
        self._browser_lock = asyncio.Lock()

    def supports(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and parsed.hostname in self.CONTENT_HOSTS and (
            self._content_id(url) is not None or self._episode_id(url) is not None
        )

    def is_manga_url(self, url: str) -> bool:
        return self._content_id(url) is not None

    def is_chapter_url(self, url: str) -> bool:
        return self._episode_id(url) is not None and "/viewer/" in urlparse(url).path

    @classmethod
    def _content_id(cls, url: str) -> int | None:
        match = cls.CONTENT_RE.search(urlparse(url).path)
        return int(match.group(1)) if match else None

    @classmethod
    def _episode_id(cls, url: str) -> int | None:
        match = cls.VIEWER_RE.search(urlparse(url).path)
        return int(match.group(2)) if match else None

    @classmethod
    def _viewer_url(cls, seo_id: str, episode_id: int) -> str:
        return f"{cls.VIEWER_ROOT}/{seo_id}/{episode_id}"

    @staticmethod
    def _cover_url(content: dict[str, Any]) -> str | None:
        cover = content.get("thumbnailImage") or content.get("sharingThumbnailImage") or content.get("backgroundImage")
        if not isinstance(cover, str) or not cover:
            return None
        if "kakaopagecdn.com" in cover and "." not in cover.rsplit("/", 1)[-1]:
            return f"{cover}.webp"
        return cover

    async def _ensure_browser(self) -> Page:
        if self._page and not self._page.is_closed():
            return self._page
        self._playwright = await async_playwright().start()
        executable = self.settings.kakao_browser_executable or shutil.which("chromium") or shutil.which("google-chrome")
        launch_kwargs: dict[str, Any] = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        if executable:
            launch_kwargs["executable_path"] = executable
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context(
            user_agent=self.settings.user_agent,
            locale="ko-KR",
            extra_http_headers={"Accept-Language": "ko"},
        )
        self._page = await self._context.new_page()
        started = time.monotonic()
        try:
            await self._page.goto("https://webtoon.kakao.com/", wait_until="commit", timeout=min(self._timeout_ms(), 15_000))
        except PlaywrightTimeoutError as exc:
            raise SourceUnavailable("Kakao page took too long to open") from exc
        log.info("Kakao browser ready elapsed=%.2fs", time.monotonic() - started)
        return self._page

    def _timeout_ms(self) -> int:
        return int(self.settings.kakao_browser_timeout_seconds * 1000)

    async def _ensure_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            timeout = aiohttp.ClientTimeout(total=15.0, connect=5.0, sock_connect=5.0, sock_read=15.0)
            self._http_session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "Accept": "application/json",
                    "Accept-Language": "ko",
                    "Origin": "https://webtoon.kakao.com",
                    "Referer": "https://webtoon.kakao.com/",
                    "User-Agent": self.settings.user_agent,
                },
                trust_env=True,
            )
        return self._http_session

    async def _direct_api_json(self, path: str) -> dict[str, Any]:
        started = time.monotonic()
        session = await self._ensure_http_session()
        try:
            async with session.get(f"{self.API_ROOT}{path}") as response:
                payload = await response.json(content_type=None)
                status = response.status
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise NetworkError("Kakao could not be reached") from exc
        log.info("Kakao direct API completed path=%s status=%s elapsed=%.2fs", path.split("?", 1)[0], status, time.monotonic() - started)
        if status != 200 or not isinstance(payload, dict):
            if status in {401, 403}:
                raise SourceUnavailable("Kakao did not expose this data to an anonymous reader")
            raise NetworkError(f"Kakao API returned status {status}")
        return payload

    async def close(self) -> None:
        async with self._browser_lock:
            if self._http_session and not self._http_session.closed:
                await self._http_session.close()
                self._http_session = None
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            self._playwright = None
            self._browser = None
            self._context = None
            self._page = None

    async def _api_json(self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        started = time.monotonic()
        page = await self._ensure_browser()
        url = f"{self.API_ROOT}{path}"
        request = {"url": url, "method": method, "payload": payload}
        try:
            result = await page.evaluate(
                """async ({url, method, payload}) => {
                    const controller = new AbortController();
                    const timer = setTimeout(() => controller.abort(), 15000);
                    let response;
                    try {
                        response = await fetch(url, {
                            method,
                            headers: {"accept": "application/json", "content-type": "application/json", "accept-language": "ko"},
                            body: method === "GET" ? undefined : JSON.stringify(payload || {}),
                            signal: controller.signal,
                        });
                    } finally {
                        clearTimeout(timer);
                    }
                    const text = await response.text();
                    let data = null;
                    try { data = JSON.parse(text); } catch (_) {}
                    return {status: response.status, data, text: text.slice(0, 500)};
                }""",
                request,
            )
        except (PlaywrightTimeoutError, OSError) as exc:
            raise NetworkError("Kakao could not be reached") from exc
        log.info("Kakao API completed path=%s status=%s elapsed=%.2fs", path.split("?", 1)[0], result.get("status"), time.monotonic() - started)
        if result.get("status") != 200 or not isinstance(result.get("data"), dict):
            status = result.get("status", "unknown")
            if status in {401, 403}:
                raise SourceUnavailable("Kakao did not expose this data to an anonymous reader")
            raise NetworkError(f"Kakao API returned status {status}")
        return result["data"]

    async def _content(self, content_id: int) -> dict[str, Any]:
        payload = await self._direct_api_json(f"/decorator/v2/decorator/contents/{content_id}/profile")
        content = payload.get("data")
        if not isinstance(content, dict) or not content.get("title"):
            raise MangaNotFound("Kakao webtoon information was not found")
        return content

    async def _episode_media(self, episode_id: int) -> dict[str, Any]:
        payload = {
            "download": False,
            "id": episode_id,
            "nonce": random.random().__str__().replace("0.", "", 1),
            "timestamp": str(int(time.time() * 1000)),
            "type": "AES_CBC_WEBP",
            "webAppId": f"KP.{episode_id}.{int(time.time() * 1000)}",
        }
        result = await self._api_json(
            f"/episode/v1/views/viewer/episodes/{episode_id}/media-resources",
            method="POST",
            payload=payload,
        )
        data = result.get("data")
        if not isinstance(data, dict):
            raise ChapterNotFound("Kakao episode information was not found")
        return data

    async def get_manga_info(self, url: str) -> MangaInfo:
        if not self.supports(url):
            raise InvalidKakaoURL("Use a Kakao Webtoon content or viewer URL")
        content_id = self._content_id(url)
        if content_id is None:
            async with self._browser_lock:
                episode_id = self._episode_id(url)
                if episode_id is None:
                    raise InvalidKakaoURL("Use a Kakao Webtoon content or viewer URL")
                media_data = await self._episode_media(episode_id)
                episode = media_data.get("episode") or {}
                content_id = int(episode.get("contentId") or 0)
        content = await self._content(content_id)
        return MangaInfo(
            title=str(content.get("title") or "Kakao Webtoon"),
            url=url,
            source="Kakao",
            cover_url=self._cover_url(content),
            status=content.get("status") or "Unknown",
            description=content.get("synopsis"),
        )

    @staticmethod
    def _chapter_number(episode: dict[str, Any]) -> str:
        title = str(episode.get("title") or "")
        match = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)", title)
        if match:
            return match.group(1)
        return str(episode.get("no") or episode.get("seasonEpisodeNo") or "unknown")

    async def get_chapters(self, url: str) -> list[Chapter]:
        content_id = self._content_id(url)
        if content_id is None:
            raise InvalidKakaoURL("Use a Kakao Webtoon content URL to browse chapters")
        chapters: list[Chapter] = []
        offset = 0
        limit = 100
        while True:
            payload = await self._direct_api_json(
                f"/episode/v2/views/content-home/contents/{content_id}/episodes?sort=NO&offset={offset}&limit={limit}"
            )
            data = payload.get("data") or {}
            episodes = data.get("episodes") if isinstance(data, dict) else None
            if not isinstance(episodes, list):
                raise ChapterNotFound("Kakao did not return a chapter list")
            for episode in episodes:
                if not isinstance(episode, dict) or not episode.get("id") or not episode.get("seoId"):
                    continue
                if not episode.get("readable"):
                    continue
                episode_id = int(episode["id"])
                chapters.append(
                    Chapter(
                        number=self._chapter_number(episode),
                        title=str(episode.get("title") or f"Chapter {self._chapter_number(episode)}"),
                        url=self._viewer_url(str(episode["seoId"]), episode_id),
                    )
                )
            if len(episodes) < limit:
                break
            offset += len(episodes)
            if offset > 50_000:
                break
        if not chapters:
            raise ChapterNotFound("No publicly readable Kakao chapters were available")
        return chapters

    async def get_chapter(self, url: str) -> Chapter:
        if not self.is_chapter_url(url):
            raise InvalidKakaoURL("Use a Kakao Webtoon viewer URL for a direct chapter")
        episode_id = self._episode_id(url)
        if episode_id is None:
            raise ChapterNotFound("Kakao episode was not found")
        async with self._browser_lock:
            media_data = await self._episode_media(episode_id)
        episode = media_data.get("episode") or {}
        if not episode or not episode.get("readable"):
            raise EpisodeNotReadable("This Kakao episode is not publicly readable")
        number = self._chapter_number(episode)
        return Chapter(number=number, title=str(episode.get("title") or f"Chapter {number}"), url=url)

    @staticmethod
    def _data_url_bytes(data_url: str) -> tuple[bytes, str]:
        match = re.match(r"^data:([^;,]*);base64,(.+)$", data_url, re.DOTALL)
        if not match:
            raise DownloadFailed("Kakao viewer returned an invalid image")
        try:
            data = base64.b64decode(match.group(2), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise DownloadFailed("Kakao viewer returned invalid image data") from exc
        if data.startswith(b"\\xff\\xd8\\xff"):
            return data, ".jpg"
        if data.startswith(b"\\x89PNG\\r\\n\\x1a\\n"):
            return data, ".png"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return data, ".gif"
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return data, ".webp"
        if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {b"avif", b"avis"}:
            return data, ".avif"
        mime = match.group(1).lower()
        if mime.startswith("image/"):
            subtype = mime.split("/", 1)[1]
            return data, ".jpg" if subtype in {"jpg", "jpeg"} else f".{subtype}"
        raise DownloadFailed("Kakao viewer returned an unknown image format")

    async def download_chapter(
        self,
        chapter: Chapter,
        destination: Path,
        progress: Progress,
        on_progress: Callable[[], Awaitable[None]] | None = None,
    ) -> list[Path]:
        episode_id = self._episode_id(chapter.url)
        if episode_id is None:
            raise InvalidKakaoURL("Kakao chapter URL is invalid")
        destination.mkdir(parents=True, exist_ok=True)
        async with self._browser_lock:
            media_data = await self._episode_media(episode_id)
            episode = media_data.get("episode") or {}
            if not episode.get("readable"):
                raise EpisodeNotReadable("This Kakao episode is not publicly readable")
            files = (media_data.get("media") or {}).get("files")
            expected = len(files) if isinstance(files, list) else 0
            if expected <= 0:
                raise ImagesNotFound("Kakao did not return readable episode images")
            progress.total = expected
            progress.current = 0
            progress.bytes_downloaded = 0
            if on_progress:
                await on_progress()
            page = await self._ensure_browser()
            try:
                try:
                    await page.goto(
                        chapter.url,
                        wait_until="commit",
                        timeout=min(self._timeout_ms(), 15_000),
                    )
                except PlaywrightTimeoutError:
                    # Kakao can keep viewer resources open indefinitely. The
                    # document may still be usable, so continue to the image
                    # readiness check instead of failing at navigation.
                    log.warning("Kakao viewer navigation timed out; checking rendered images")
                await page.wait_for_function(
                    "expected => document.querySelectorAll('div[data-index] img[src^=\\\"blob:http\\\"]').length >= expected",
                    arg=expected,
                    timeout=self._timeout_ms(),
                )
                data_urls = await page.evaluate(
                    """async () => {
                        const blobUrls = Array.from(
                            document.querySelectorAll('div[data-index] img[src^="blob:http"]'),
                            image => image.src,
                        );
                        return await Promise.all(blobUrls.map(async blobUrl => {
                            const response = await fetch(blobUrl);
                            const blob = await response.blob();
                            return await new Promise((resolve, reject) => {
                                const reader = new FileReader();
                                reader.onload = () => resolve(reader.result);
                                reader.onerror = reject;
                                reader.readAsDataURL(blob);
                            });
                        }));
                    }"""
                )
            except PlaywrightTimeoutError as exc:
                raise ImagesNotFound("Kakao viewer did not render all readable images") from exc
            if len(data_urls) < expected:
                raise ImagesNotFound("Kakao viewer returned an incomplete readable episode")
            paths: list[Path] = []
            for index, data_url in enumerate(data_urls[:expected], 1):
                data, extension = self._data_url_bytes(data_url)
                path = destination / f"{index:03d}{extension}"
                path.write_bytes(data)
                paths.append(path)
                progress.current = index
                progress.bytes_downloaded += len(data)
                progress.update_speed()
                if on_progress:
                    await on_progress()

            merged_dir = destination / ".merged"
            merged_paths = merge_naver_images(paths, merged_dir)
            for path in paths:
                path.unlink(missing_ok=True)
            ordered_paths: list[Path] = []
            for index, path in enumerate(merged_paths, 1):
                target = destination / f"{index:03d}{path.suffix.lower()}"
                path.replace(target)
                ordered_paths.append(target)
            shutil.rmtree(merged_dir, ignore_errors=True)
            return ordered_paths
