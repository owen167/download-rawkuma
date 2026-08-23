from __future__ import annotations

from pathlib import Path
from typing import Protocol


class StorageAdapter(Protocol):
    async def publish(self, path: Path) -> str | Path:
        ...


class LocalStorage:
    async def publish(self, path: Path) -> Path:
        return path
