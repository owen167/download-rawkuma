from __future__ import annotations

from pathlib import Path
from typing import Protocol


class StorageAdapter(Protocol):
    async def publish_directory(self, directory: Path, display_name: str) -> str:
        ...


class LocalStorage:
    async def publish_directory(self, directory: Path, display_name: str) -> str:
        return str(directory)
