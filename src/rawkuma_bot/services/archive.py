from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

from rawkuma_bot.downloaders.models import Chapter, MangaInfo


def safe_name(value: str, fallback: str = "untitled") -> str:
    value = re.sub(r"[^\w\-. ]+", "_", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return (value[:120] or fallback)


def build_archive(manga: MangaInfo, chapter: Chapter, images_dir: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manga_name = safe_name(manga.title)
    chapter_name = f"Chapter_{chapter.number:03g}"
    archive = output_dir / f"{manga_name}_Chapter_{chapter.number:03g}.zip"
    staging = output_dir / f".staging_{manga_name}_{chapter.number:g}"
    shutil.rmtree(staging, ignore_errors=True)
    nested = staging / manga_name / chapter_name
    nested.mkdir(parents=True, exist_ok=True)
    for image in sorted(images_dir.iterdir(), key=lambda path: path.name):
        shutil.copy2(image, nested / image.name)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
        for file_path in sorted(nested.rglob("*")):
            if file_path.is_file():
                bundle.write(file_path, file_path.relative_to(staging).as_posix())
    shutil.rmtree(staging, ignore_errors=True)
    return archive
