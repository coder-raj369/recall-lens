"""Find label, barcode and rating-plate regions with OWLv2 zero-shot detection (Apache-2.0).

Requires the optional `ml` dependency group.
"""

from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING

from recall_lens.perception import torch_device

if TYPE_CHECKING:  # Pillow is in the optional ml group; box logic must import without it
    from PIL import Image

MODEL_ID = "google/owlv2-base-patch16-ensemble"
QUERIES = (
    "a product label with printed text",
    "a barcode",
    "a rating plate with model and serial number",
    "a sticker with a lot number",
)
THRESHOLD = 0.2
MAX_REGIONS = 4
NMS_IOU = 0.5

Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class Region:
    box: Box  # x0, y0, x1, y1 in image pixels
    query: str
    score: float


@cache
def _load():
    from transformers import Owlv2ForObjectDetection, Owlv2Processor

    device, _ = torch_device()
    model = Owlv2ForObjectDetection.from_pretrained(MODEL_ID).to(
        device
    )  # float32: boxes stay precise
    return Owlv2Processor.from_pretrained(MODEL_ID), model.eval(), device


def iou(a: Box, b: Box) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def suppress(regions: list[Region], max_iou: float = NMS_IOU) -> list[Region]:
    """Greedy non-maximum suppression across all queries, highest score first."""
    kept: list[Region] = []
    for region in sorted(regions, key=lambda r: -r.score):
        if all(iou(region.box, k.box) <= max_iou for k in kept):
            kept.append(region)
    return kept


def detect(
    image: "Image.Image", threshold: float = THRESHOLD, max_regions: int = MAX_REGIONS
) -> list[Region]:
    """Most confident, non-overlapping label-like regions in the image."""
    import torch

    processor, model, device = _load()
    inputs = processor(text=[list(QUERIES)], images=image, return_tensors="pt").to(device)
    with torch.inference_mode():
        outputs = model(**inputs)
    # OWLv2 pads the image to a square at the bottom and right, so boxes are relative to it.
    side = max(image.size)
    (result,) = processor.image_processor.post_process_object_detection(
        outputs, threshold=threshold, target_sizes=[(side, side)]
    )
    width, height = image.size
    regions = []
    for score, label, box in zip(result["scores"], result["labels"], result["boxes"], strict=True):
        x0, y0, x1, y1 = (round(float(v)) for v in box)
        clipped = (max(0, x0), max(0, y0), min(width, x1), min(height, y1))
        if clipped[2] - clipped[0] > 8 and clipped[3] - clipped[1] > 8:
            regions.append(Region(clipped, QUERIES[int(label)], float(score)))
    return suppress(regions)[:max_regions]
