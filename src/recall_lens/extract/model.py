"""Zero-shot identifier extraction with GLiNER, for mentions that carry no explicit label.

Requires the optional `ml` dependency group (`uv sync --group ml`).
"""

import re
from functools import cache

from recall_lens.ingest.models import Identifier, identifier

MODEL_ID = "urchade/gliner_medium-v2.1"  # Apache-2.0
LABELS = {
    "brand name": "brand",
    "model number": "model",
    "lot number": "lot",
    "UPC barcode number": "upc",
}
THRESHOLD = 0.5
# ponytail: one pass over the opening text (GLiNER reads ~384 words); identifiers named later
# in very long reports are left to the rules. Window the text if recall suffers.
MAX_CHARS = 1_500

_LABEL_PREFIX = re.compile(
    r"^(?:(?:model|lot|batch|upc|sku|product|serial|code|number|no\.?)\b|[#:\s])+", re.IGNORECASE
)


@cache
def _model():
    from gliner import GLiNER  # heavy optional import

    return GLiNER.from_pretrained(MODEL_ID)


def _clean(kind: str, text: str) -> Identifier | None:
    if kind != "brand":
        text = _LABEL_PREFIX.sub("", text)
        if not any(c.isdigit() for c in text):
            return None
    return identifier(kind, text)


def extract(text: str | None, threshold: float = THRESHOLD) -> set[Identifier]:
    if not text:
        return set()
    entities = _model().predict_entities(text[:MAX_CHARS], list(LABELS), threshold=threshold)
    return {ident for e in entities if (ident := _clean(LABELS[e["label"]], e["text"]))}
