#!/usr/bin/env python3
"""Download all-MiniLM-L6-v2 ONNX model for Pliny embeddings.

Downloads pre-exported ONNX model from HuggingFace (onnx-community)
and tokenizer from sentence-transformers.

Usage: python scripts/setup-model.py [--model-dir ~/.pliny/models]
"""

import argparse
import os
import sys
import urllib.request
from pathlib import Path

MODEL_URL = "https://huggingface.co/onnx-community/all-MiniLM-L6-v2-ONNX/resolve/main/onnx/model.onnx"
MODEL_DATA_URL = "https://huggingface.co/onnx-community/all-MiniLM-L6-v2-ONNX/resolve/main/onnx/model.onnx_data"
TOKENIZER_URL = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/tokenizer.json"


def download(url, dest, label):
    if dest.exists():
        print(f"  {label} already exists ({dest.stat().st_size / 1_000_000:.1f} MB)")
        return
    print(f"  Downloading {label}...")
    try:
        urllib.request.urlretrieve(url, dest)
    except Exception as e:
        print(f"  Failed: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Download embedding model for Pliny")
    parser.add_argument(
        "--model-dir",
        default=os.path.expanduser("~/.pliny/models"),
        help="Directory to store model files",
    )
    args = parser.parse_args()

    model_dir = Path(args.model_dir) / "all-MiniLM-L6-v2"
    model_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading model to {model_dir}/")
    download(MODEL_URL, model_dir / "model.onnx", "model.onnx")
    download(MODEL_DATA_URL, model_dir / "model.onnx_data", "model.onnx_data")
    download(TOKENIZER_URL, model_dir / "tokenizer.json", "tokenizer.json")

    total_mb = sum(f.stat().st_size for f in model_dir.iterdir() if f.is_file()) / 1_000_000
    print(f"\nModel ready: {model_dir}/")
    for f in sorted(model_dir.iterdir()):
        if f.is_file():
            print(f"  {f.name} ({f.stat().st_size / 1_000_000:.1f} MB)")
    print(f"  Total: {total_mb:.1f} MB")
    print(f"\nEmbeddings are now available. Set PLINY_MODEL_DIR={args.model_dir}")


if __name__ == "__main__":
    main()
