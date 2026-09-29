"""Perception: turn product photos into identifiers."""


def torch_device() -> tuple[str, object]:
    """Best available device and a dtype suited to it (float16 on Apple GPUs, else float32)."""
    import torch

    if torch.backends.mps.is_available():
        return "mps", torch.float16
    if torch.cuda.is_available():
        return "cuda", torch.float16
    return "cpu", torch.float32
