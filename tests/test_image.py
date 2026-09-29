import io

import pytest

Image = pytest.importorskip("PIL.Image")

from recall_lens.perception.image import load  # noqa: E402


def encode(image, **save_args):
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", **save_args)
    return buffer.getvalue()


def test_applies_exif_rotation():
    landscape = Image.new("RGB", (40, 20), "white")
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90 degrees clockwise to display
    assert load(encode(landscape, exif=exif)).size == (20, 40)


def test_converts_to_rgb_and_caps_size(tmp_path):
    path = tmp_path / "big.png"
    Image.new("RGBA", (5000, 1000), (255, 0, 0, 128)).save(path)
    image = load(path, max_side=1000)
    assert image.mode == "RGB"
    assert image.size == (1000, 200)


def test_small_images_are_not_upscaled():
    assert load(encode(Image.new("RGB", (300, 200)))).size == (300, 200)
