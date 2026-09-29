"""Turn a product photo into identifiers: OCR the photo and its label regions, then extract.

Requires the optional `ml` dependency group.
"""

import re
from dataclasses import dataclass

from PIL import Image

from recall_lens.extract import rules
from recall_lens.ingest.models import Identifier

# OCR spacing artifacts that break labeled-code rules: "Model No .: S-Y608", "T30 -F".
BARCODE_SCALES = (1, 2, 4)
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.:#])")
_SPACED_HYPHEN = re.compile(
    r"(?<=\d) ?- ?(?=[A-Za-z0-9])|(?<=[A-Za-z0-9]) ?- ?(?=\d)"
)  # codes have digits


@dataclass(frozen=True)
class Reading:
    texts: tuple[str, ...]  # full-photo text first, then one per detected region
    identifiers: frozenset[Identifier]  # typed: labeled codes (rules) and brands (GLiNER)
    codes: frozenset[str]  # every code-like value, labeled or bare, kind unknown

    @property
    def text(self) -> str:
        return "\n".join(self.texts)


def normalize(text: str) -> str:
    return _SPACED_HYPHEN.sub("-", _SPACE_BEFORE_PUNCT.sub(r"\1", text))


def read(image: Image.Image, use_detection: bool = True, use_model: bool = True) -> Reading:
    """Read a photo. Detection adds OCR of each label region, which recovers small print."""
    from recall_lens.perception import barcode, ocr

    texts, upcs = [ocr.read_text(image)], barcode.decode(image)
    if use_detection:
        from recall_lens.perception.crop import crop
        from recall_lens.perception.detect import detect

        for region in detect(image):
            patch = crop(image, region.box)
            texts.append(ocr.read_text(patch))
            # Small barcodes decode only once enlarged; decoding takes milliseconds.
            for scale in BARCODE_SCALES:
                size = (patch.width * scale, patch.height * scale)
                upcs |= barcode.decode(patch.resize(size, Image.Resampling.LANCZOS))
    text = "\n".join(normalize(t) for t in texts)
    identifiers = rules.extract(text) | {("upc", upc) for upc in upcs}
    if use_model:
        from recall_lens.extract import model

        # On label text GLiNER also tags serial and model codes as brands; drop code-like ones.
        brands = model.extract(text, model.BRAND_ONLY)
        identifiers |= {
            (k, v) for k, v in brands if not (" " not in v and any(c.isdigit() for c in v))
        }
    return Reading(tuple(texts), frozenset(identifiers), frozenset(rules.codes(text) | upcs))
