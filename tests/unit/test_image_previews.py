from pathlib import Path

import pytest
from PIL import Image

from src.utils import images as image_utils


def _save_rgb(path: Path, size: tuple[int, int], *, fmt: str | None = None) -> None:
    Image.new("RGB", size, (220, 40, 40)).save(path, format=fmt)


@pytest.fixture
def preview_600(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(image_utils, "PREVIEW_SIZES", (600,))


def _preview_path(src: Path, size: int = 600) -> Path:
    return src.with_name(f"{src.stem}_{size}{src.suffix}")


def _assert_resized(src: Path, expected: tuple[int, int], size: int = 600) -> None:
    preview = _preview_path(src, size)
    assert preview.is_file()
    with Image.open(preview) as img:
        assert img.size == expected
    assert preview.read_bytes() != src.read_bytes()


@pytest.mark.parametrize(
    ("suffix", "fmt"),
    [(".jpg", "JPEG"), (".png", "PNG"), (".webp", "WEBP")],
)
def test_preview_resizes_large_image(
    tmp_path: Path, preview_600: None, suffix: str, fmt: str
) -> None:
    src = tmp_path / f"photo{suffix}"
    _save_rgb(src, (2000, 1000), fmt=fmt)
    image_utils._generate_previews(src)
    _assert_resized(src, (600, 300))
    assert _preview_path(src).stat().st_size < src.stat().st_size


def test_preview_keeps_aspect_ratio(tmp_path: Path, preview_600: None) -> None:
    src = tmp_path / "photo.jpg"
    _save_rgb(src, (2000, 1000), fmt="JPEG")
    image_utils._generate_previews(src)
    with Image.open(_preview_path(src)) as img:
        width, height = img.size
    assert width / height == pytest.approx(2.0)


def test_preview_does_not_upscale(tmp_path: Path, preview_600: None) -> None:
    src = tmp_path / "photo.jpg"
    _save_rgb(src, (400, 300), fmt="JPEG")
    image_utils._generate_previews(src)
    with Image.open(_preview_path(src)) as img:
        assert img.size == (400, 300)


def test_preview_png_keeps_alpha(tmp_path: Path, preview_600: None) -> None:
    src = tmp_path / "logo.png"
    Image.new("RGBA", (800, 400), (255, 0, 0, 128)).save(src)
    image_utils._generate_previews(src)
    preview = _preview_path(src)
    with Image.open(preview) as img:
        assert img.size == (600, 300)
        assert img.mode in {"RGBA", "LA"}
        assert img.getpixel((0, 0))[3] < 255
    assert preview.read_bytes() != src.read_bytes()


def test_preview_exif_orientation_is_applied(tmp_path: Path, preview_600: None) -> None:
    src = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (100, 200), (0, 0, 220))
    exif = image.getexif()
    exif[0x0112] = 6
    image.save(src, format="JPEG", exif=exif)
    image_utils._generate_previews(src)
    with Image.open(_preview_path(src)) as img:
        assert img.size == (200, 100)


def test_preview_naming_keeps_existing_sizes(tmp_path: Path) -> None:
    src = tmp_path / "abc.jpg"
    _save_rgb(src, (1200, 600), fmt="JPEG")
    image_utils._generate_previews(src)
    with Image.open(tmp_path / "abc_300.jpg") as img:
        assert img.size == (300, 150)
    with Image.open(tmp_path / "abc_600.jpg") as img:
        assert img.size == (600, 300)
    with Image.open(tmp_path / "abc_900.jpg") as img:
        assert img.size == (900, 450)
