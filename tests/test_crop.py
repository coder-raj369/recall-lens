import pytest

Image = pytest.importorskip("PIL.Image")

from recall_lens.perception.crop import crop  # noqa: E402


def test_crop_pads_box_and_letterboxes_to_square():
    image = Image.new("RGB", (1000, 500), "black")
    square = crop(image, (100, 100, 300, 150))  # a 200 x 50 strip
    assert square.size == (240, 240)  # 10% padding: 240 x 60, centered on a square
    assert square.getpixel((120, 120)) == (0, 0, 0)  # the strip
    assert square.getpixel((120, 5)) == (255, 255, 255)  # letterbox margin


def test_crop_stays_inside_the_image():
    image = Image.new("RGB", (100, 100), "black")
    assert crop(image, (0, 0, 100, 40)).size == (100, 100)
