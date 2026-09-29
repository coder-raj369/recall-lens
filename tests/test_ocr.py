import pytest

pytest.importorskip("transformers")
Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")
ImageFont = pytest.importorskip("PIL.ImageFont")
hub = pytest.importorskip("huggingface_hub")

from recall_lens.perception import ocr  # noqa: E402

if not hub.try_to_load_from_cache(ocr.MODEL_ID, "config.json"):
    pytest.skip("Florence-2 weights are not downloaded", allow_module_level=True)


def test_reads_a_printed_label():
    image = Image.new("RGB", (900, 300), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=48)
    draw.text((30, 40), "Model No: AB-1234", fill="black", font=font)
    draw.text((30, 150), "Lot: 5678X", fill="black", font=font)
    text = ocr.read_text(image).upper().replace(" ", "")
    assert "AB-1234" in text and "5678X" in text
