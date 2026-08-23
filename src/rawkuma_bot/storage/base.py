from __future__ import annotations

from pathlib import Path
from typing import Protocol


class StorageAdapter(Protocol):
    async def publish_file(self, path: Path, display_name: str) -> str:
        ...


class LocalStorage:
    async def publish_file(self, path: Path, display_name: str) -> str:
        return str(path)
