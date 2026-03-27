"""Tests for the embedding service."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — we always mock sentence_transformers so tests don't need the
# 80 MB model download.
# ---------------------------------------------------------------------------

def _fake_encode(texts, show_progress_bar=False):
    """Return deterministic fake embeddings (numpy-like lists)."""
    import numpy as np

    if isinstance(texts, str):
        texts = [texts]
        single = True
    else:
        single = False

    # Simple hash-based fake embedding (dimension 8 for speed)
    vectors = []
    for t in texts:
        h = hash(t) & 0xFFFFFFFF
        rng = __import__("random").Random(h)
        vec = [rng.gauss(0, 1) for _ in range(8)]
        norm = sum(x * x for x in vec) ** 0.5
        vec = [x / norm for x in vec]
        vectors.append(vec)

    arr = np.array(vectors)
    if single:
        return arr[0]
    return arr


def _make_mock_st():
    """Build a mock SentenceTransformer class."""
    mock_cls = MagicMock()
    instance = MagicMock()
    instance.encode = _fake_encode
    mock_cls.return_value = instance
    return mock_cls


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def embedding_svc():
    """Return a fresh EmbeddingService with a mocked model."""
    from trellis.embeddings import EmbeddingService

    svc = EmbeddingService(model_name="mock-model")
    # Directly inject a fake model that has an .encode method
    fake_model = MagicMock()
    fake_model.encode = _fake_encode
    svc._model = fake_model
    svc._available = True
    yield svc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEmbed:
    def test_returns_list_of_floats(self, embedding_svc):
        vec = embedding_svc.embed("hello world")
        assert vec is not None
        assert isinstance(vec, list)
        assert all(isinstance(v, float) for v in vec)

    def test_vector_length(self, embedding_svc):
        vec = embedding_svc.embed("test text")
        assert vec is not None
        assert len(vec) == 8  # our fake embedding dimension


class TestSimilarity:
    def test_similar_texts_score_higher(self, embedding_svc):
        # Same text should be maximally similar
        v1 = embedding_svc.embed("schedule a doctor appointment")
        v2 = embedding_svc.embed("schedule a doctor appointment")
        v3 = embedding_svc.embed("quantum physics lecture notes")

        sim_same = embedding_svc.similarity(v1, v2)
        sim_diff = embedding_svc.similarity(v1, v3)

        assert sim_same > sim_diff
        assert sim_same == pytest.approx(1.0, abs=0.01)

    def test_none_vectors_return_zero(self, embedding_svc):
        assert embedding_svc.similarity(None, [1.0, 2.0]) == 0.0
        assert embedding_svc.similarity([1.0, 2.0], None) == 0.0

    def test_mismatched_lengths_return_zero(self, embedding_svc):
        assert embedding_svc.similarity([1.0], [1.0, 2.0]) == 0.0

    def test_zero_vectors_return_zero(self, embedding_svc):
        assert embedding_svc.similarity([0.0, 0.0], [0.0, 0.0]) == 0.0


class TestBatchEmbed:
    def test_returns_correct_count(self, embedding_svc):
        texts = ["hello", "world", "test"]
        result = embedding_svc.batch_embed(texts)
        assert result is not None
        assert len(result) == 3
        assert all(isinstance(v, list) for v in result)

    def test_each_vector_has_floats(self, embedding_svc):
        result = embedding_svc.batch_embed(["a", "b"])
        assert result is not None
        for vec in result:
            assert all(isinstance(x, float) for x in vec)


class TestGracefulFallback:
    def test_embed_returns_none_when_unavailable(self):
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            from trellis.embeddings import EmbeddingService

            svc = EmbeddingService()
            svc._available = None  # reset
            # Force import to fail
            with patch("builtins.__import__", side_effect=ImportError("no module")):
                result = svc.embed("test")
                assert result is None

    def test_batch_embed_returns_none_when_unavailable(self):
        from trellis.embeddings import EmbeddingService

        svc = EmbeddingService()
        svc._available = False
        assert svc.batch_embed(["a", "b"]) is None

    def test_similarity_handles_none_gracefully(self):
        from trellis.embeddings import EmbeddingService

        assert EmbeddingService.similarity(None, None) == 0.0

    def test_available_property_false_when_no_model(self):
        from trellis.embeddings import EmbeddingService

        svc = EmbeddingService()
        svc._available = False
        assert svc.available is False


class TestSingleton:
    def test_module_level_singleton_exists(self):
        from trellis.embeddings import embedding_service, EmbeddingService

        assert isinstance(embedding_service, EmbeddingService)

    def test_singleton_is_stable_across_imports(self):
        from trellis.embeddings import embedding_service as svc1
        from trellis.embeddings import embedding_service as svc2

        assert svc1 is svc2
