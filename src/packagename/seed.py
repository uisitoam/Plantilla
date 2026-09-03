"""Seeding of every random number generator the project may touch."""

from __future__ import annotations

import logging
import os
import random
from contextlib import suppress

import numpy as np

__all__ = ["set_seed"]

logger = logging.getLogger(__name__)


def set_seed(seed: int, *, deterministic: bool = False) -> int:
    """Seed Python, NumPy and, when installed, PyTorch and TensorFlow.

    Args:
        seed: The seed to apply.
        deterministic: Also disable non-deterministic GPU kernels. This makes
            results bit-reproducible at a higher cost in throughput.

    Returns:
        The seed that was applied, so callers can log it in one expression.
    """
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)  # noqa: NPY002 -- seeds the legacy global RNG that libraries still use

    _seed_torch(seed, deterministic=deterministic)
    _seed_tensorflow(seed)

    logger.debug("Random seed set to %d (deterministic=%s)", seed, deterministic)
    return seed


def _seed_torch(seed: int, *, deterministic: bool) -> None:
    try:
        import torch
    except ImportError:
        return

    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if deterministic:
        # cuBLAS needs this set before the first CUDA context is created.
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        with suppress(RuntimeError):
            torch.use_deterministic_algorithms(True)


def _seed_tensorflow(seed: int) -> None:
    try:
        import tensorflow as tf
    except ImportError:
        return

    tf.random.set_seed(seed)
