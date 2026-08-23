from pathlib import Path

from PIL import Image

from rawkuma_bot.services.naver_image_merge import merge_naver_images


def _make_image(path: Path, size: tuple[int, int], image_format: str) -> None:
    mode = "RGB" if image_format in {"JPEG", "WEBP"} else "RGBA"
    image = Image.new(mode, size, (20, 40, 60) if mode == "RGB" else (20, 40, 60, 255))
    image.save(path, format=image_format)
    image.close()


def test_merges_pages_vertically_in_order_and_caps_height(tmp_path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "merged"
    source_dir.mkdir()
    first = source_dir / "001.jpg"
    second = source_dir / "002.jpg"
    third = source_dir / "003.jpg"
    _make_image(first, (100, 8000), "JPEG")
    _make_image(second, (120, 7000), "JPEG")
    _make_image(third, (80, 2000), "JPEG")

    merged = merge_naver_images([first, second, third], output_dir)

    assert [path.name for path in merged] == [".merged_001.jpg", ".merged_002.jpg"]
    with Image.open(merged[0]) as image:
        assert image.size == (120, 14000)
    with Image.open(merged[1]) as image:
        assert image.size == (120, 3000)
    assert all(Image.open(path).format == "JPEG" for path in merged)


def test_keeps_webp_output_format(tmp_path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "merged"
    source_dir.mkdir()
    first = source_dir / "001.webp"
    second = source_dir / "002.webp"
    _make_image(first, (80, 30), "WEBP")
    _make_image(second, (80, 40), "WEBP")

    merged = merge_naver_images([first, second], output_dir, max_height=100)

    assert merged[0].suffix == ".webp"
    with Image.open(merged[0]) as image:
        assert image.format == "WEBP"
        assert image.size == (80, 70)
