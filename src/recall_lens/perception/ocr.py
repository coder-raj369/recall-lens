"""Read text from photos with Florence-2 (MIT), using its native transformers implementation.

Florence-2 resizes every input to 768 x 768, so small print on a large photo can become
unreadable; reading detected label regions (see perception.detect) addresses that.
Requires the optional `ml` dependency group.
"""

from functools import cache

from PIL import Image

from recall_lens.perception import torch_device

MODEL_ID = "florence-community/Florence-2-large"
TASK = "<OCR>"


@cache
def _load():
    from transformers import AutoProcessor, Florence2ForConditionalGeneration

    device, dtype = torch_device()
    model = Florence2ForConditionalGeneration.from_pretrained(MODEL_ID, dtype=dtype).to(device)
    return AutoProcessor.from_pretrained(MODEL_ID), model.eval(), device, dtype


def read_text(image: Image.Image, max_new_tokens: int = 512) -> str:
    """Return the text Florence-2 reads in the image, in reading order."""
    import torch

    processor, model, device, dtype = _load()
    inputs = processor(text=TASK, images=image, return_tensors="pt").to(device)
    with torch.inference_mode():
        generated = model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"].to(dtype),
            max_new_tokens=max_new_tokens,
            num_beams=3,
            do_sample=False,
        )
    raw = processor.batch_decode(generated, skip_special_tokens=False)[0]
    parsed = processor.post_process_generation(raw, task=TASK, image_size=image.size)
    return parsed[TASK].strip()
