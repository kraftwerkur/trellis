"""Semantic embedding service for intelligent routing.

Provides vector embeddings via sentence-transformers for semantic similarity
matching between user requests and agent capabilities. Degrades gracefully
to keyword-only routing if the library or model is unavailable.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "all-MiniLM-L6-v2"


class EmbeddingService:
    """Lazy-loading embedding service with graceful fallback.

    Uses sentence-transformers to produce dense vector embeddings.
    The model is loaded on first call, not at import time, so the
    service never blocks startup.  If sentence-transformers is not
    installed or the model cannot be loaded, every method returns a
    safe default (None / 0.0) and logs a warning once.
    """

    def __init__(self, model_name: Optional[str] = None) -> None:
        self._model_name = (
            model_name
            or os.environ.get("TRELLIS_EMBEDDING_MODEL")
            or DEFAULT_MODEL
        )
        self._model = None
        self._available: Optional[bool] = None  # None = not yet checked

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_model(self) -> bool:
        """Load the model on first use.  Returns True if ready."""
        if self._available is True:
            return True
        if self._available is False:
            return False

        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
            self._available = True
            logger.info(
                "Embedding model '%s' loaded successfully.", self._model_name
            )
            return True
        except ImportError:
            self._available = False
            logger.warning(
                "sentence-transformers is not installed. "
                "Semantic routing will fall back to keyword matching."
            )
            return False
        except Exception as exc:  # noqa: BLE001
            self._available = False
            logger.warning(
                "Failed to load embedding model '%s': %s. "
                "Semantic routing will fall back to keyword matching.",
                self._model_name,
                exc,
            )
            return False

    @property
    def available(self) -> bool:
        """Whether the embedding model is loaded and usable."""
        if self._available is None:
            self._ensure_model()
        return bool(self._available)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(self, text: str) -> Optional[list[float]]:
        """Return the embedding vector for *text*, or None on failure."""
        if not self._ensure_model():
            return None
        try:
            vector = self._model.encode(text, show_progress_bar=False)
            return vector.tolist()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Embedding failed for text: %s", exc)
            return None

    def batch_embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """Return embedding vectors for a batch of texts, or None."""
        if not self._ensure_model():
            return None
        try:
            vectors = self._model.encode(texts, show_progress_bar=False)
            return [v.tolist() for v in vectors]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Batch embedding failed: %s", exc)
            return None

    @staticmethod
    def similarity(
        v1: Optional[list[float]], v2: Optional[list[float]]
    ) -> float:
        """Cosine similarity between two vectors.  Returns 0.0 on error."""
        if v1 is None or v2 is None:
            return 0.0
        if len(v1) != len(v2) or len(v1) == 0:
            return 0.0
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        return dot / (norm1 * norm2)


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------
embedding_service = EmbeddingService()
