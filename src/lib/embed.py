"""Embedding helpers — ONNX-accelerated all-MiniLM-L6-v2 with PyTorch fallback."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

try:
    # Try ONNX Runtime path (faster, lower memory)
    import torch
    from optimum.onnxruntime import ORTModelForFeatureExtraction
    from transformers import AutoTokenizer

    _MODE = "onnx"

    MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "models" / "onnx" / "all-MiniLM-L6-v2"
    _ONNX_MODEL: ORTModelForFeatureExtraction | None = None
    _ONNX_TOKENIZER: "AutoTokenizer" | None = None
except ImportError:
    _MODE = "pytorch"
    _ONNX_MODEL = None
    _ONNX_TOKENIZER = None

if _MODE == "pytorch":
    # Fallback: standard sentence-transformers
    from sentence_transformers import SentenceTransformer

    _PYTORCH_MODEL: SentenceTransformer | None = None

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIMS = 384


def _load_onnx():
    global _ONNX_MODEL, _ONNX_TOKENIZER
    if _ONNX_MODEL is None:
        model_path = str(MODEL_DIR)
        _ONNX_MODEL = ORTModelForFeatureExtraction.from_pretrained(
            model_path, local_files_only=True
        )
        _ONNX_TOKENIZER = AutoTokenizer.from_pretrained(model_path, local_files_only=True)


def _load_pytorch():
    global _PYTORCH_MODEL
    if _PYTORCH_MODEL is None:
        _PYTORCH_MODEL = SentenceTransformer(MODEL_NAME)


def _mean_pooling(token_embeddings: torch.Tensor, attention_mask: torch.Tensor) -> np.ndarray:
    """Mean pooling + normalization for ONNX outputs."""
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, dim=1)
    sum_mask = torch.clamp(input_mask_expanded.sum(dim=1), min=1e-9)
    embeddings = sum_embeddings / sum_mask
    # L2 normalize
    embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
    return embeddings.detach().cpu().numpy()


def embed(text: str) -> list[float]:
    """Return 384-dim normalized embedding for text."""
    if _MODE == "onnx":
        _load_onnx()
        inputs = _ONNX_TOKENIZER(
            text, return_tensors="pt",
            padding=True, truncation=True, max_length=256,
        )
        with torch.no_grad():
            outputs = _ONNX_MODEL(**inputs)
        embeddings = _mean_pooling(outputs.last_hidden_state, inputs["attention_mask"])
        return embeddings[0].tolist()
    else:
        _load_pytorch()
        return _PYTORCH_MODEL.encode(text, normalize_embeddings=True).tolist()


def embed_json(text: str) -> str:
    """Return embedding as JSON array string (for vec0 INSERT)."""
    return json.dumps(embed(text))
