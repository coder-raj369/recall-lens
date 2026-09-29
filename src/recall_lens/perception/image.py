"""Load photos into upright RGB images of bounded size.

Requires the optional `ml` dependency group (Pillow).
"""

import io
from pathlib import Path

from PIL import Image, ImageOps

from recall_lens.ingest.http import fetch

# Phone photos run to 12+ megapixels; label text stays legible at this size and models downscale
# further anyway, so larger inputs only cost memory.
MAX_SIDE = 2048


def load(source: str | Path | bytes, max_side: int = MAX_SIDE) -> Image.Image:
    """Open a photo from a path, URL or raw bytes, apply its EXIF rotation and cap its size."""
    if isinstance(source, bytes):
        data = source
    elif isinstance(source, str) and source.startswith(("http://", "https://")):
        data = fetch(source, timeout=120)
    else:
        data = Path(source).read_bytes()
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return image
