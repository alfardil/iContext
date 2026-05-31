"""Lazy-loaded sentence-transformers embedding model.

Model: `sentence-transformers/all-MiniLM-L6-v2` — 384-dim, ~22 MB, CPU/MPS friendly.
Embeddings are L2-normalized so cosine similarity == 1 - 0.5 * (L2 distance)^2.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIM = 384

_model: "SentenceTransformer | None" = None
_load_lock = threading.Lock()


def _ensure_model() -> "SentenceTransformer":
    global _model
    if _model is not None:
        return _model
    with _load_lock:
        if _model is not None:
            return _model
        from sentence_transformers import SentenceTransformer

        log.info("Loading embedding model %s (one-time, ~2s)…", MODEL_NAME)
        _model = SentenceTransformer(MODEL_NAME)
        log.info("Embedding model ready.")
        return _model


def embed(texts: list[str], batch_size: int = 64) -> "np.ndarray":
    """Encode `texts` and return an (n, 384) float32 array of unit vectors."""
    import numpy as np

    model = _ensure_model()
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vectors.astype(np.float32)


def warmup() -> None:
    """Eagerly load the model. Cheap to call multiple times."""
    _ensure_model()
