from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Awaitable, Callable


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    PROCESSING = "PROCESSING"
    PACKAGING = "PACKAGING"
    UPLOADING = "UPLOADING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(slots=True, frozen=True)
class Chapter:
    # Keep the exact chapter label from Rawkuma, including decimals such as 10.354.
    number: str
    title: str
    url: str

    @property
    def sort_key(self) -> Decimal:
        try:
            return Decimal(self.number)
        except (InvalidOperation, ValueError):
            return Decimal("-Infinity")


@dataclass(slots=True, frozen=True)
class MangaInfo:
    title: str
    url: str
    source: str = "Rawkuma"
    cover_url: str | None = None
    status: str | None = None
    description: str | None = None


@dataclass(slots=True, frozen=True)
class ImageRef:
    number: int
    url: str
    extension: str = ".jpg"


@dataclass(slots=True)
class Progress:
    current: int = 0
    total: int = 0
    bytes_downloaded: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    speed_bps: float = 0.0

    @property
    def percent(self) -> float:
        return (self.current / self.total * 100) if self.total else 0.0

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, (datetime.now(timezone.utc) - self.started_at).total_seconds())

    def update_speed(self) -> None:
        elapsed = self.elapsed_seconds
        self.speed_bps = self.bytes_downloaded / elapsed if elapsed else 0.0


ProgressCallback = Callable[["DownloadJob"], Awaitable[None]]


@dataclass(slots=True)
class DownloadJob:
    user_id: int
    guild_id: int
    manga: MangaInfo
    chapter: Chapter
    job_id: str
    url: str
    status: JobStatus = JobStatus.QUEUED
    progress: Progress = field(default_factory=Progress)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    image_count: int = 0
    archive_path: Path | None = None
    archive_size_bytes: int = 0
    upload_url: str | None = None
