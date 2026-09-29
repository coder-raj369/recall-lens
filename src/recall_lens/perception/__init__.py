"""Perception: turn product photos into identifiers."""


def torch_device() -> tuple[str, object]:
    """Best available device and a dtype suited to it (float16 on Apple GPUs, else float32)."""
    import torch

    if torch.backends.mps.is_available():
        return "mps", torch.float16
    if torch.cuda.is_available():
        return "cuda", torch.float16
    return "cpu", torch.float32


def release_models() -> None:
    """Unload perception models: with bge-m3 they do not fit in 8 GB alongside Postgres."""
    import gc

    from recall_lens.extract import model
    from recall_lens.perception import detect, ocr

    for loader in (ocr._load, detect._load, model._model):
        loader.cache_clear()
    gc.collect()
