from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from rawkuma_bot.config.settings import Settings
from rawkuma_bot.downloaders.models import DownloadJob, JobStatus, MangaInfo, Chapter, Progress
from rawkuma_bot.downloaders.rawkuma.downloader import RawkumaDownloader
from .archive import build_archive

log = logging.getLogger(__name__)
ProgressHandler = Callable[[DownloadJob], Awaitable[None]]


class DownloadManager:
    def __init__(self, settings: Settings, downloader: RawkumaDownloader, on_progress: ProgressHandler | None = None) -> None:
        self.settings = settings
        self.downloader = downloader
        self.on_progress = on_progress
        self.queue: asyncio.Queue[DownloadJob] = asyncio.Queue()
        self.jobs: dict[str, DownloadJob] = {}
        self.workers: list[asyncio.Task] = []
        self._completion_events: dict[str, asyncio.Event] = {}

    async def start(self) -> None:
        # Chapter jobs are intentionally sequential: the next chapter starts only
        # after the previous chapter has been uploaded and its completion Embed sent.
        log.info("Starting download workers count=1 sequential_mode=true")
        self.workers = [asyncio.create_task(self._worker(), name="rawkuma-worker-0")]

    async def stop(self) -> None:
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()

    async def submit(self, user_id: int, guild_id: int, manga: MangaInfo, chapter: Chapter) -> DownloadJob:
        job = DownloadJob(user_id, guild_id, manga, chapter, uuid.uuid4().hex, manga.url)
        self.jobs[job.job_id] = job
        self._completion_events[job.job_id] = asyncio.Event()
        await self.queue.put(job)
        log.info("Job queued id=%s user=%s chapter=%s queue_size=%d", job.job_id, user_id, chapter.number, self.queue.qsize())
        await self._emit(job)
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return False
        job.status = JobStatus.CANCELLED
        log.info("Job cancelled id=%s", job_id)
        return True

    async def wait_for_completion(self, job: DownloadJob) -> DownloadJob:
        event = self._completion_events[job.job_id]
        await event.wait()
        self._completion_events.pop(job.job_id, None)
        return job

    async def _emit(self, job: DownloadJob) -> None:
        if self.on_progress:
            await self.on_progress(job)

    async def _worker(self) -> None:
        while True:
            job = await self.queue.get()
            try:
                await self._run(job)
            except asyncio.CancelledError:
                job.status = JobStatus.CANCELLED
                await self._emit(job)
                raise
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error = type(exc).__name__
                job.finished_at = datetime.now(timezone.utc)
                log.exception("Job %s failed", job.job_id)
                await self._emit(job)
            finally:
                completion_event = self._completion_events.get(job.job_id)
                if completion_event:
                    completion_event.set()
                self.queue.task_done()

    async def _run(self, job: DownloadJob) -> None:
        if job.status == JobStatus.CANCELLED:
            return
        job.status = JobStatus.DOWNLOADING
        job.started_at = datetime.now(timezone.utc)
        log.info("Job started id=%s chapter=%s", job.job_id, job.chapter.number)
        await self._emit(job)
        temp_job = self.settings.temp_dir / f"job_{job.job_id}" / f"chapter_{job.chapter.number}"
        try:
            files = await self.downloader.download_chapter(job.chapter, temp_job, job.progress)
            job.image_count = len(files)
            job.status = JobStatus.PROCESSING
            await self._emit(job)
            job.status = JobStatus.PACKAGING
            await self._emit(job)
            job.archive_path = build_archive(job.manga, job.chapter, temp_job, self.settings.output_dir)
            job.archive_size_bytes = job.archive_path.stat().st_size
            log.info("Job packaged id=%s images=%d archive_bytes=%d", job.job_id, job.image_count, job.archive_size_bytes)
            job.status = JobStatus.UPLOADING
            await self._emit(job)
            job.status = JobStatus.COMPLETED
            job.finished_at = datetime.now(timezone.utc)
            log.info("Job completed id=%s chapter=%s", job.job_id, job.chapter.number)
            await self._emit(job)
        finally:
            shutil.rmtree(self.settings.temp_dir / f"job_{job.job_id}", ignore_errors=True)

    def active_jobs(self) -> list[DownloadJob]:
        return [job for job in self.jobs.values() if job.status not in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}]
