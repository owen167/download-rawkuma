from pathlib import Path

import pytest

from rawkuma_bot.config.settings import Settings
from rawkuma_bot.downloaders.models import Chapter, MangaInfo, Progress
from rawkuma_bot.services.manager import DownloadManager


class FakeDownloader:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self.events = events

    async def download_chapter(self, chapter: Chapter, destination: Path, progress: Progress, on_progress=None) -> list[Path]:
        self.events.append(("download_started", chapter.number))
        destination.mkdir(parents=True, exist_ok=True)
        page = destination / "001.webp"
        page.write_bytes(b"page")
        progress.total = 1
        if on_progress:
            await on_progress()
        progress.current = 1
        if on_progress:
            await on_progress()
        self.events.append(("download_finished", chapter.number))
        return [page]


@pytest.mark.asyncio
async def test_selected_chapters_run_sequentially(tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []

    async def on_progress(job) -> None:
        if job.status.value in {"DOWNLOADING", "COMPLETED"}:
            events.append((job.status.value.lower(), job.chapter.number))

    settings = Settings(temp_dir=tmp_path / "temp", output_dir=tmp_path / "output", max_concurrent_downloads=5)
    manager = DownloadManager(settings, FakeDownloader(events), on_progress)
    await manager.start()

    manga = MangaInfo("Demo", "https://rawkuma.net/manga/demo/")
    first = await manager.submit(1, 2, manga, Chapter("1", "Chapter 1", "https://rawkuma.net/chapter-1"))
    second = await manager.submit(1, 2, manga, Chapter("2", "Chapter 2", "https://rawkuma.net/chapter-2"))
    await manager.wait_for_completion(first)
    await manager.wait_for_completion(second)
    await manager.stop()

    assert len(manager.workers) == 0
    assert events.index(("completed", "1")) < events.index(("downloading", "2"))
    assert events.index(("completed", "2")) > events.index(("downloading", "2"))


@pytest.mark.asyncio
async def test_each_job_can_use_a_different_downloader(tmp_path: Path) -> None:
    default_events: list[tuple[str, str]] = []
    naver_events: list[tuple[str, str]] = []
    default_downloader = FakeDownloader(default_events)
    naver_downloader = FakeDownloader(naver_events)
    settings = Settings(temp_dir=tmp_path / "temp", output_dir=tmp_path / "output")
    manager = DownloadManager(settings, default_downloader)
    await manager.start()

    rawkuma_manga = MangaInfo("Raw", "https://rawkuma.net/manga/demo")
    naver_manga = MangaInfo("Naver", "https://comic.naver.com/webtoon/list?titleId=807777", source="Naver")
    raw_job = await manager.submit(1, 2, rawkuma_manga, Chapter("1", "Chapter 1", "https://rawkuma.net/chapter-1"))
    naver_job = await manager.submit(
        1,
        2,
        naver_manga,
        Chapter("40", "Chapter 40", "https://comic.naver.com/webtoon/detail?titleId=807777&no=40"),
        downloader=naver_downloader,
    )
    await manager.wait_for_completion(raw_job)
    await manager.wait_for_completion(naver_job)
    await manager.stop()

    assert default_events == [("download_started", "1"), ("download_finished", "1")]
    assert naver_events == [("download_started", "40"), ("download_finished", "40")]
