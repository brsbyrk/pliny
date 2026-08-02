"""Test embed module — embed(), embed_json() with mock models.

No actual model loading — all model calls are mocked via sys.modules.
"""

import json
import sys
from unittest.mock import patch, MagicMock

import pytest
import numpy as np


def _mock_sentence_transformers():
    """Mock the sentence_transformers module to allow embed.py to import."""
    if "sentence_transformers" not in sys.modules:
        mock_st = MagicMock()
        mock_st.SentenceTransformer = MagicMock()
        sys.modules["sentence_transformers"] = mock_st
    if "optimum.onnxruntime" not in sys.modules:
        mock_onnx = MagicMock()
        sys.modules["optimum"] = MagicMock()
        sys.modules["optimum.onnxruntime"] = mock_onnx


class TestEmbedPytorch:
    def test_embed_returns_384_dim(self):
        """embed() should return 384 floats when using PyTorch fallback."""
        _mock_sentence_transformers()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.ones(384, dtype=np.float32)

        from src.lib import embed as embed_mod
        # Force PyTorch mode
        embed_mod._MODE = "pytorch"
        embed_mod._PYTORCH_MODEL = mock_model

        result = embed_mod.embed("test text")
        assert len(result) == 384
        assert all(isinstance(v, float) for v in result)
        mock_model.encode.assert_called_once_with(
            "test text", normalize_embeddings=True
        )

    def test_embed_json_returns_string(self):
        """embed_json() should return a JSON array string."""
        _mock_sentence_transformers()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros(384, dtype=np.float32)

        from src.lib import embed as embed_mod
        embed_mod._MODE = "pytorch"
        embed_mod._PYTORCH_MODEL = mock_model

        result = embed_mod.embed_json("test text")
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert len(parsed) == 384


class TestEmbedConstants:
    def test_dims_is_384(self):
        _mock_sentence_transformers()
        from src.lib.embed import DIMS
        assert DIMS == 384

    def test_model_name(self):
        _mock_sentence_transformers()
        from src.lib.embed import MODEL_NAME
        assert "all-MiniLM-L6-v2" in MODEL_NAME


class TestMeanPooling:
    def test_mean_pooling_output_shape(self):
        """_mean_pooling should produce correct shape."""
        _mock_sentence_transformers()
        import torch
        from src.lib.embed import _mean_pooling

        token_embeddings = torch.randn(1, 5, 384)
        attention_mask = torch.ones(1, 5, dtype=torch.long)

        result = _mean_pooling(token_embeddings, attention_mask)
        assert isinstance(result, np.ndarray)
        assert result.shape == (1, 384)

    def test_mean_pooling_masked(self):
        """_mean_pooling with partial mask."""
        _mock_sentence_transformers()
        import torch
        from src.lib.embed import _mean_pooling

        token_embeddings = torch.ones(1, 5, 384)
        attention_mask = torch.tensor([[1, 1, 1, 0, 0]], dtype=torch.long)

        result = _mean_pooling(token_embeddings, attention_mask)
        assert result.shape == (1, 384)
        norm = float(np.linalg.norm(result[0]))
        assert abs(norm - 1.0) < 1e-4

    def test_mean_pooling_all_zeros_mask(self):
        """_mean_pooling with all-zero mask should not divide by zero."""
        _mock_sentence_transformers()
        import torch
        from src.lib.embed import _mean_pooling

        token_embeddings = torch.ones(1, 5, 384)
        attention_mask = torch.zeros(1, 5, dtype=torch.long)
        result = _mean_pooling(token_embeddings, attention_mask)
        assert result.shape == (1, 384)
