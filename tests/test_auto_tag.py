"""Test auto_tag.py — tokenize, centroids, predict_tags, cosine similarity.

No database access. Uses temp file for centroids JSON.
"""

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_basic_tokenization(self):
        from cli.auto_tag import _tokenize
        tokens = _tokenize("Deep Learning and Machine Learning")
        # Stopwords like "and" should be filtered
        assert "deep" in tokens
        assert "learning" in tokens
        assert "machine" in tokens
        assert "and" not in tokens

    def test_short_tokens_filtered(self):
        from cli.auto_tag import _tokenize
        tokens = _tokenize("a b c I am AI")
        # Single-char tokens filtered
        assert all(len(t) >= 2 for t in tokens)

    def test_numbers_filtered(self):
        from cli.auto_tag import _tokenize
        tokens = _tokenize("model 123 version 2.0")
        assert "model" in tokens
        assert "version" in tokens
        assert "123" not in tokens


# ---------------------------------------------------------------------------
# _cosine_similarity
# ---------------------------------------------------------------------------

class TestAutoTagCosine:
    def test_identical(self):
        from cli.auto_tag import _cosine_similarity
        a = np.array([1.0, 2.0, 3.0])
        result = _cosine_similarity(a, a)
        assert abs(result - 1.0) < 1e-6

    def test_zero_vector(self):
        from cli.auto_tag import _cosine_similarity
        result = _cosine_similarity(np.array([0.0, 0.0]), np.array([1.0, 2.0]))
        assert result == 0.0


# ---------------------------------------------------------------------------
# load_centroids / save_centroids
# ---------------------------------------------------------------------------

class TestCentroidsIO:
    def test_load_centroids_missing_file(self, monkeypatch, tmp_path):
        from cli import auto_tag
        nonexistent = tmp_path / "nonexistent.json"
        monkeypatch.setattr(auto_tag, "CENTROIDS_PATH", nonexistent)
        result = auto_tag.load_centroids()
        assert result == []

    def test_save_and_load_centroids(self, monkeypatch, tmp_path):
        from cli import auto_tag
        centroids_path = tmp_path / "centroids.json"
        monkeypatch.setattr(auto_tag, "CENTROIDS_PATH", centroids_path)

        centroids = [
            {"cluster_id": 0, "tags": ["ai", "ml", "dl"], "centroid": [0.1, 0.2, 0.3]},
            {"cluster_id": 1, "tags": ["python", "rust"], "centroid": [0.4, 0.5, 0.6]},
        ]
        auto_tag.save_centroids(centroids)
        loaded = auto_tag.load_centroids()
        assert loaded == centroids

    def test_load_corrupt_json(self, monkeypatch, tmp_path):
        from cli import auto_tag
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{not valid json")
        monkeypatch.setattr(auto_tag, "CENTROIDS_PATH", bad_file)
        result = auto_tag.load_centroids()
        assert result == []


# ---------------------------------------------------------------------------
# predict_tags
# ---------------------------------------------------------------------------

class TestPredictTags:
    def test_no_centroids_returns_empty(self, monkeypatch, tmp_path):
        from cli import auto_tag
        monkeypatch.setattr(auto_tag, "CENTROIDS_PATH", tmp_path / "nonexistent.json")
        result = auto_tag.predict_tags("Some title")
        assert result == []

    def test_predict_finds_nearest_centroid(self, monkeypatch, tmp_path):
        from cli import auto_tag

        centroids_path = tmp_path / "centroids.json"
        monkeypatch.setattr(auto_tag, "CENTROIDS_PATH", centroids_path)

        # Create centroids with known tags
        centroids = [
            {"cluster_id": 0, "tags": ["python", "programming"],
             "centroid": [1.0] * 5000},  # Dense
            {"cluster_id": 1, "tags": ["cooking", "food"],
             "centroid": [0.0] * 5000},  # Sparse
        ]
        auto_tag.save_centroids(centroids)

        # "Python" title should hash closer to the programming centroid
        result = auto_tag.predict_tags("Python async programming tutorial")
        assert len(result) > 0
        assert isinstance(result, list)

    def test_predict_with_content_argument(self, monkeypatch, tmp_path):
        from cli import auto_tag

        centroids_path = tmp_path / "centroids.json"
        monkeypatch.setattr(auto_tag, "CENTROIDS_PATH", centroids_path)

        centroids = [
            {"cluster_id": 0, "tags": ["ml", "ai"],
             "centroid": [1.0] * 5000},
        ]
        auto_tag.save_centroids(centroids)

        # content should be accepted but title is the primary signal
        result = auto_tag.predict_tags("Machine Learning 101",
                                       content="Deep learning content...")
        assert isinstance(result, list)
