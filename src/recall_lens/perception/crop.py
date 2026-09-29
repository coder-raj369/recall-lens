"""Crop detected regions so small print fills the OCR model's input.

Florence-2 stretches every image to 768 x 768: a wide label strip would be squashed, so crops
are letterboxed onto a square canvas instead.
"""

from PIL import Image

from recall_lens.perception.detect import Box

PAD = 0.1  # margin around each detection, as a fraction of its size; boxes are often tight


def crop(image: Image.Image, box: Box, pad: float = PAD) -> Image.Image:
    """Crop a padded box and letterbox it onto a white square."""
    x0, y0, x1, y1 = box
    dx, dy = round((x1 - x0) * pad), round((y1 - y0) * pad)
    width, height = image.size
    region = image.crop(
        (max(0, x0 - dx), max(0, y0 - dy), min(width, x1 + dx), min(height, y1 + dy))
    )
    side = max(region.size)
    square = Image.new("RGB", (side, side), "white")
    square.paste(region, ((side - region.width) // 2, (side - region.height) // 2))
    return square
