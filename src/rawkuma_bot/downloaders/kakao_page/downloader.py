from __future__ import annotations

import asyncio
import html
import logging
import mimetypes
import re
import shutil
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import aiohttp

from rawkuma_bot.config.settings import Settings
from rawkuma_bot.downloaders.models import Chapter, MangaInfo, Progress
from rawkuma_bot.services.naver_image_merge import merge_images_with_mapping
from .errors import (
    ChapterNotFound,
    ContentNotFound,
    DownloadFailed,
    InvalidKakaoPageURL,
    KakaoPageError,
    MangaNotFound,
    NetworkError,
    ProductNotReadable,
)

log = logging.getLogger(__name__)


class KakaoPageDownloader:
    """Download anonymous/free KakaoPage novel products as HTML plus public images."""

    source = "Kakao Page"
    HOST = "page.kakao.com"
    API_ROOT = "https://bff-page.kakao.com/api/gateway/api"
    ASSET_ROOT = "https://dn-img-page.kakao.com/sdownload/resource?kid="
    HOME_RE = re.compile(r"/home/[^/]+/(\d+)(?:/|$)")
    CONTENT_RE = re.compile(r"/content/(\d+)(?:/|$)")
    VIEWER_RE = re.compile(r"/content/(\d+)/viewer/(\d+)(?:/|$)")

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._session: aiohttp.ClientSession | None = None
        self._timeout = aiohttp.ClientTimeout(total=settings.request_timeout_seconds)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                headers={
                    "Accept-Language": "ko",
                    "Origin": "https://page.kakao.com",
                    "Referer": "https://page.kakao.com/",
                    "User-Agent": self.settings.user_agent,
                },
                trust_env=True,
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    @classmethod
    def _series_id(cls, url: str) -> int | None:
        parsed = urlparse(url)
        for pattern in (cls.HOME_RE, cls.CONTENT_RE):
            match = pattern.search(parsed.path)
            if match:
                return int(match.group(1))
        return None

    @classmethod
    def _product_ids(cls, url: str) -> tuple[int, int] | None:
        match = cls.VIEWER_RE.search(urlparse(url).path)
        return (int(match.group(1)), int(match.group(2))) if match else None

    @classmethod
    def supports(cls, url: str) -> bool:
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        return parsed.scheme in {"http", "https"} and parsed.hostname == cls.HOST and cls._series_id(url) is not None

    @classmethod
    def is_manga_url(cls, url: str) -> bool:
        return cls.supports(url) and cls._product_ids(url) is None

    @classmethod
    def is_chapter_url(cls, url: str) -> bool:
        return cls.supports(url) and cls._product_ids(url) is not None

    @staticmethod
    def _clean(text: Any) -> str:
        return " ".join(str(text or "").split()).strip()

    @staticmethod
    def _chapter_number(title: str, fallback: int) -> str:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:화|회|chapter|episode)", title, re.I)
        if match:
            return match.group(1)
        return str(fallback)

    async def _get_json(self, path: str) -> dict[str, Any]:
        session = await self._ensure_session()
        try:
            async with session.get(f"{self.API_ROOT}{path}") as response:
                if response.status in {401, 403}:
                    raise ProductNotReadable("Kakao Page did not expose this content anonymously")
                if response.status == 404:
                    raise ContentNotFound("Kakao Page content was not found")
                if response.status != 200:
                    raise NetworkError(f"Kakao Page returned HTTP {response.status}")
                payload = await response.json(content_type=None)
        except ProductNotReadable:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise NetworkError("Kakao Page could not be reached") from exc
        if not isinstance(payload, dict):
            raise NetworkError("Kakao Page returned invalid data")
        if payload.get("result_code") not in (None, 0):
            raise ProductNotReadable("Kakao Page did not expose this content anonymously")
        return payload

    async def _get_signed_json(self, url: str) -> dict[str, Any]:
        session = await self._ensure_session()
        try:
            async with session.get(url, headers={"Accept": "application/json", "Referer": "https://page.kakao.com/"}) as response:
                if response.status in {401, 403}:
                    raise ProductNotReadable("Kakao Page did not expose this chapter anonymously")
                if response.status != 200:
                    raise ContentNotFound("Kakao Page chapter content was not available")
                payload = await response.json(content_type=None)
        except ProductNotReadable:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise NetworkError("Kakao Page chapter content could not be read") from exc
        if not isinstance(payload, dict):
            raise ContentNotFound("Kakao Page returned invalid chapter content")
        return payload

    @classmethod
    def _asset_url(cls, root: str, key: str, filename: str | None = None) -> str:
        url = root + key
        return f"{url}&filename={filename}" if filename else url

    @staticmethod
    def _extension(filename: str | None, content_type: str | None = None) -> str:
        suffix = Path(filename or "").suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".svg"}:
            return suffix
        guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
        return guessed if guessed in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".svg"} else ".bin"

    async def get_manga_info(self, url: str) -> MangaInfo:
        if not self.is_manga_url(url):
            raise InvalidKakaoPageURL("Use a Kakao Page content URL")
        series_id = self._series_id(url)
        if series_id is None:
            raise InvalidKakaoPageURL("Use a Kakao Page content URL")
        payload = await self._get_json(
            f"/v2/content/product/list?series_id={series_id}&cursor_index=0&cursor_direction=ANCHOR&window_size=1"
        )
        result = payload.get("result") or {}
        item = result.get("series_item")
        if not isinstance(item, dict) or not item.get("title"):
            overview = await self._get_json(f"/v1/content/overview?series_id={series_id}")
            item = (overview.get("result") or {}).get("series_item")
        if not isinstance(item, dict) or not item.get("title"):
            raise MangaNotFound("Kakao Page work information was not found")
        thumbnail = item.get("thumbnail")
        cover_url = self._asset_url(self.ASSET_ROOT, str(thumbnail)) if thumbnail else None
        return MangaInfo(
            title=self._clean(item.get("title")) or "Kakao Page",
            url=url,
            source=self.source,
            cover_url=cover_url,
            status=str(item.get("state") or "Available"),
            description=self._clean(item.get("description")),
        )

    async def get_chapters(self, url: str) -> list[Chapter]:
        if not self.is_manga_url(url):
            raise InvalidKakaoPageURL("Use a Kakao Page content URL to browse chapters")
        series_id = self._series_id(url)
        if series_id is None:
            raise InvalidKakaoPageURL("Use a Kakao Page content URL")
        chapters: list[Chapter] = []
        seen: set[int] = set()
        cursor = 0
        window = 20
        while True:
            payload = await self._get_json(
                f"/v2/content/product/list?series_id={series_id}&cursor_index={cursor}&cursor_direction=ANCHOR&window_size={window}"
            )
            result = payload.get("result") or {}
            entries = result.get("list")
            if not isinstance(entries, list):
                raise ChapterNotFound("Kakao Page products were not found")
            for entry in entries:
                item = entry.get("item") if isinstance(entry, dict) else None
                if not isinstance(item, dict) or not item.get("product_id") or not item.get("is_free"):
                    continue
                product_id = int(item["product_id"])
                if product_id in seen or item.get("hidden"):
                    continue
                seen.add(product_id)
                title = self._clean(item.get("title")) or f"Chapter {len(chapters) + 1}"
                number = self._chapter_number(title, len(chapters) + 1)
                chapters.append(
                    Chapter(
                        number=number,
                        title=title,
                        url=f"https://page.kakao.com/content/{series_id}/viewer/{product_id}/",
                    )
                )
            if not result.get("has_next") or not entries:
                break
            last_cursor = entries[-1].get("cursor_index") if isinstance(entries[-1], dict) else None
            if not isinstance(last_cursor, int) or last_cursor <= cursor:
                break
            cursor = last_cursor
            if cursor > 100_000:
                break
        if not chapters:
            raise ChapterNotFound("No free anonymous Kakao Page chapters were available")
        return chapters

    async def _viewer_data(self, series_id: int, product_id: int) -> dict[str, Any]:
        return await self._get_json(f"/v1/viewer/data?series_id={series_id}&product_id={product_id}")

    async def get_chapter(self, url: str) -> Chapter:
        ids = self._product_ids(url)
        if ids is None:
            raise InvalidKakaoPageURL("Use a Kakao Page viewer URL for a direct chapter")
        series_id, product_id = ids
        payload = await self._viewer_data(series_id, product_id)
        item = payload.get("item")
        if not isinstance(item, dict) or not item.get("is_free"):
            raise ProductNotReadable("This Kakao Page product is not anonymously free")
        title = self._clean(item.get("title")) or f"Chapter {product_id}"
        return Chapter(number=self._chapter_number(title, product_id), title=title, url=url)

    @staticmethod
    def _paragraph_html(node: dict[str, Any], image_names: dict[str, str | list[str]]) -> str:
        kind = str(node.get("type") or "").upper()
        text = html.escape(str(node.get("text") or ""))
        image = node.get("image")
        if isinstance(image, dict) and image.get("imageSrcKey"):
            key = str(image["imageSrcKey"])
            names = image_names.get(key)
            if names:
                if isinstance(names, str):
                    names = [names]
                alt = html.escape(str((node.get("attributes") or {}).get("alt") or ""))
                return "".join(f'<p><img src="images/{name}" alt="{alt}"></p>' for name in names)
        children = node.get("childParagraphList")
        inner = "".join(KakaoPageDownloader._paragraph_html(child, image_names) for child in children or [] if isinstance(child, dict))
        if inner:
            if kind in {"DIV", "P", "PARAGRAPH", "TEXT"}:
                return f"<div>{text}{inner}</div>"
            return inner
        return f"<p>{text}</p>" if text else ""

    @staticmethod
    def _collect_images(node: dict[str, Any], output: list[dict[str, str]], seen: set[str]) -> None:
        image = node.get("image")
        if isinstance(image, dict) and image.get("imageSrcKey"):
            key = str(image["imageSrcKey"])
            if key not in seen:
                seen.add(key)
                output.append({
                    "key": key,
                    "filename": str(image.get("imageFilename") or "image"),
                })
        children = node.get("childParagraphList")
        for child in children or []:
            if isinstance(child, dict):
                KakaoPageDownloader._collect_images(child, output, seen)

    async def _download_asset(self, url: str, target: Path, referer: str) -> None:
        session = await self._ensure_session()
        last_error: Exception | None = None
        for attempt in range(1, self.settings.retry_attempts + 1):
            try:
                async with session.get(url, headers={"Accept": "image/*,*/*;q=0.8", "Referer": referer}) as response:
                    if response.status in {401, 403}:
                        raise ProductNotReadable("Kakao Page did not expose a public image")
                    if response.status != 200:
                        raise DownloadFailed(f"Kakao Page image returned HTTP {response.status}")
                    with target.open("wb") as output:
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            output.write(chunk)
                if target.stat().st_size == 0:
                    raise DownloadFailed("Kakao Page returned an empty image")
                return
            except ProductNotReadable:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, KakaoPageError) as exc:
                last_error = exc
                target.unlink(missing_ok=True)
                if attempt < self.settings.retry_attempts:
                    await asyncio.sleep(self.settings.retry_backoff_seconds * attempt)
        raise DownloadFailed("Kakao Page image failed after retries") from last_error

    async def download_chapter(
        self,
        chapter: Chapter,
        destination: Path,
        progress: Progress,
        on_progress: Callable[[], Awaitable[None]] | None = None,
    ) -> list[Path]:
        ids = self._product_ids(chapter.url)
        if ids is None:
            raise InvalidKakaoPageURL("Kakao Page chapter URL is invalid")
        series_id, product_id = ids
        payload = await self._viewer_data(series_id, product_id)
        item = payload.get("item")
        viewer = payload.get("viewer_data")
        if not isinstance(item, dict) or not item.get("is_free"):
            raise ProductNotReadable("This Kakao Page product is not anonymously free")
        if not isinstance(viewer, dict) or not viewer.get("contents_list"):
            raise ContentNotFound("Kakao Page did not expose readable chapter content")
        root = str(viewer.get("ats_server_url") or self.ASSET_ROOT).replace("http://", "https://", 1)
        content_docs: list[dict[str, Any]] = []
        for content in viewer["contents_list"]:
            secure = content.get("secure_url") if isinstance(content, dict) else None
            if not secure:
                continue
            content_docs.append(await self._get_signed_json(root + str(secure)))
        if not content_docs:
            raise ContentNotFound("Kakao Page chapter content was not available")
        image_refs: list[dict[str, str]] = []
        seen: set[str] = set()
        has_content = False
        for document in content_docs:
            info = document.get("contentInfo") if isinstance(document, dict) else None
            if not isinstance(info, dict):
                continue
            paragraphs = info.get("paragraphList") or []
            has_content = has_content or bool(paragraphs)
            for node in paragraphs:
                if isinstance(node, dict):
                    self._collect_images(node, image_refs, seen)
        if not has_content and not image_refs:
            raise ContentNotFound("Kakao Page chapter contained no readable content")
        destination.mkdir(parents=True, exist_ok=True)
        source_dir = destination / ".source"
        source_dir.mkdir(parents=True, exist_ok=True)
        progress.total = len(image_refs) + 1
        progress.current = 0
        progress.bytes_downloaded = 0
        if on_progress:
            await on_progress()
        semaphore = asyncio.Semaphore(self.settings.max_concurrent_pages)
        downloaded: list[Path | None] = [None] * len(image_refs)

        async def fetch_one(index: int, ref: dict[str, str]) -> None:
            async with semaphore:
                target = source_dir / f"{index + 1:03d}{self._extension(ref['filename'])}"
                await self._download_asset(self._asset_url(root, ref["key"], ref["filename"]), target, chapter.url)
                downloaded[index] = target
                progress.current += 1
                progress.bytes_downloaded += target.stat().st_size
                progress.update_speed()
                if on_progress:
                    await on_progress()

        try:
            await asyncio.gather(*(fetch_one(index, ref) for index, ref in enumerate(image_refs)))
            source_paths = [path for path in downloaded if path is not None]
            merged_dir = destination / ".merged"
            merged_paths, _source_mapping = merge_images_with_mapping(source_paths, merged_dir)
            final_paths: list[Path] = []
            merged_to_final: dict[Path, Path] = {}
            images_dir = destination / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            for index, path in enumerate(merged_paths, 1):
                target = images_dir / f"{index:03d}{path.suffix.lower()}"
                path.replace(target)
                merged_to_final[path] = target
                final_paths.append(target)
            for path in source_paths:
                path.unlink(missing_ok=True)
            shutil.rmtree(source_dir, ignore_errors=True)
            shutil.rmtree(merged_dir, ignore_errors=True)
            image_names: dict[str, list[str]] = {}
            for index, ref in enumerate(image_refs):
                image_names[ref["key"]] = [merged_to_final[path].name for path in _source_mapping.get(index, []) if path in merged_to_final]
            fragments: list[str] = []
            for document in content_docs:
                info = document.get("contentInfo") if isinstance(document, dict) else None
                for node in (info or {}).get("paragraphList") or []:
                    if isinstance(node, dict):
                        fragments.append(self._paragraph_html(node, image_names))
            chapter_title = html.escape(str(item.get("title") or chapter.title))
            document = "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><title>" + chapter_title + "</title><style>body{max-width:900px;margin:2rem auto;padding:0 1rem;line-height:1.8;font-family:system-ui,sans-serif}img{max-width:100%;height:auto;display:block;margin:1rem auto}</style></head><body><h1>" + chapter_title + "</h1>" + "".join(fragments) + "</body></html>"
            html_path = destination / "chapter.html"
            html_path.write_text(document, encoding="utf-8")
            progress.current += 1
            progress.bytes_downloaded += html_path.stat().st_size
            progress.update_speed()
            if on_progress:
                await on_progress()
            return [html_path, *final_paths]
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise
