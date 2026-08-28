from __future__ import annotations

import numpy as np

from app.cache.semantic_cache import cosine_similarity, normalize_query_text


def test_normalize_query_text() -> None:
    assert normalize_query_text("  How  MANY   Critical? ") == "how many critical?"


def test_cosine_similarity_identical() -> None:
    vector = [0.1, 0.2, 0.3]
    assert cosine_similarity(vector, vector) == 1.0


def test_cosine_similarity_orthogonal() -> None:
    score = cosine_similarity([1.0, 0.0], [0.0, 1.0])
    assert abs(score) < 1e-6


def test_cosine_similarity_threshold_band() -> None:
    base = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    near = np.array([0.98, 0.2, 0.0], dtype=np.float32)
    near = near / np.linalg.norm(near)
    score = cosine_similarity(base, near)
    assert score >= 0.92
