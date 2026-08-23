from __future__ import annotations

from pathlib import Path

from PIL import Image

NAVER_MERGED_IMAGE_MAX_HEIGHT = 14_000

_FORMATS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".avif": "AVIF",
    ".gif": "GIF",
}


def _format_for(path: Path) -> str:
    image_format = _FORMATS.get(path.suffix.lower())
    if not image_format:
        raise ValueError(f"Unsupported Naver image format: {path.suffix}")
    return image_format


def _canvas_mode(image_format: str) -> tuple[str, tuple[int, ...]]:
    if image_format in {"JPEG", "GIF"}:
        return "RGB", (255, 255, 255)
    return "RGBA", (0, 0, 0, 0)


def _extension_for(image_format: str) -> str:
    for extension, value in _FORMATS.items():
        if value == image_format:
            return extension
    raise ValueError(f"Unsupported output format: {image_format}")


def merge_naver_images(
    image_paths: list[Path],
    output_dir: Path,
    *,
    max_height: int = NAVER_MERGED_IMAGE_MAX_HEIGHT,
) -> list[Path]:
    """Stack ordered Naver pages vertically into format-preserving strips."""
    if not image_paths:
        raise ValueError("No Naver images to merge")
    if max_height <= 0:
        raise ValueError("max_height must be positive")

    output_dir.mkdir(parents=True, exist_ok=True)
    max_width = 0
    for path in image_paths:
        with Image.open(path) as image:
            max_width = max(max_width, image.width)
    if max_width <= 0:
        raise ValueError("Naver images have no usable width")

    # Each segment records source files and vertical slices. This avoids keeping
    # all pages in memory while making the 14,000px boundary deterministic.
    segments: list[tuple[Path, int, int]] = []
    segment_height = 0
    segment_format: str | None = None
    segment_extension: str | None = None
    output_paths: list[Path] = []

    def flush_segment() -> None:
        nonlocal segment_height, segment_format, segment_extension, segments
        if not segments or segment_format is None:
            return
        mode, background = _canvas_mode(segment_format)
        canvas = Image.new(mode, (max_width, segment_height), background)
        y = 0
        for source_path, top, height in segments:
            with Image.open(source_path) as source:
                source.load()
                crop = source.crop((0, top, source.width, top + height))
                if mode == "RGB":
                    crop = crop.convert("RGB")
                else:
                    crop = crop.convert("RGBA")
                canvas.paste(crop, (0, y))
                crop.close()
            y += height
        output_path = output_dir / f".merged_{len(output_paths) + 1:03d}{segment_extension or _extension_for(segment_format)}"
        save_kwargs: dict[str, object] = {}
        if segment_format == "JPEG":
            save_kwargs = {"quality": 95, "optimize": False}
        elif segment_format == "WEBP":
            save_kwargs = {"lossless": True}
        canvas.save(output_path, format=segment_format, **save_kwargs)
        canvas.close()
        output_paths.append(output_path)
        segments = []
        segment_height = 0
        segment_format = None
        segment_extension = None

    for source_path in image_paths:
        image_format = _format_for(source_path)
        with Image.open(source_path) as source:
            source_width, source_height = source.size
        if source_width <= 0 or source_height <= 0:
            raise ValueError(f"Naver image is empty: {source_path.name}")
        top = 0
        while top < source_height:
            if segment_format not in {None, image_format}:
                flush_segment()
            room = max_height - segment_height
            if room == 0:
                flush_segment()
                room = max_height
            part_height = min(source_height - top, room)
            if segment_format is None:
                segment_format = image_format
                segment_extension = source_path.suffix.lower()
            segments.append((source_path, top, part_height))
            segment_height += part_height
            top += part_height
            if segment_height == max_height:
                flush_segment()
    flush_segment()
    return output_paths
