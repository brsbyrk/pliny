#!/usr/bin/env python3
"""Download all-MiniLM-L6-v2 and export to ONNX (opset 14, dynamo=false).

Usage: python scripts/setup-model.py [--model-dir ~/.pliny/models]
"""

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Setup embedding model for Pliny")
    parser.add_argument(
        "--model-dir",
        default=os.path.expanduser("~/.pliny/models"),
        help="Directory to store model files",
    )
    args = parser.parse_args()

    model_dir = Path(args.model_dir) / "all-MiniLM-L6-v2"
    model_path = model_dir / "model.onnx"
    tokenizer_path = model_dir / "tokenizer.json"

    if model_path.exists() and tokenizer_path.exists():
        print(f"✓ Model already exists at {model_dir}")
        print(f"  model.onnx:  {model_path.stat().st_size / 1_000_000:.1f} MB")
        print(f"  tokenizer.json: {tokenizer_path.stat().st_size / 1000:.1f} KB")
        return

    print("Installing dependencies...")
    os.system(f"{sys.executable} -m pip install -q sentence-transformers transformers torch onnx")

    model_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading model from HuggingFace...")
    from sentence_transformers import SentenceTransformer
    import torch

    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    # Export to ONNX
    print("Exporting to ONNX (opset=14, dynamo=False)...")
    dummy_input = model.tokenizer(
        "test sentence",
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=256,
    )

    # Get the underlying transformer model
    transformer = model._first_module()

    with torch.no_grad():
        torch.onnx.export(
            transformer,
            (
                dummy_input["input_ids"],
                dummy_input["attention_mask"],
                dummy_input.get("token_type_ids", torch.zeros_like(dummy_input["input_ids"])),
            ),
            str(model_path),
            input_names=["input_ids", "attention_mask", "token_type_ids"],
            output_names=["last_hidden_state"],
            dynamic_axes={
                "input_ids": {0: "batch", 1: "sequence"},
                "attention_mask": {0: "batch", 1: "sequence"},
                "token_type_ids": {0: "batch", 1: "sequence"},
                "last_hidden_state": {0: "batch", 1: "sequence"},
            },
            opset_version=14,
            dynamo=False,
        )

    # Save tokenizer
    print("Saving tokenizer.json...")
    model.tokenizer.save(str(tokenizer_path))

    size_mb = model_path.stat().st_size / 1_000_000
    print(f"\n✓ Model exported successfully!")
    print(f"  {model_dir}/")
    print(f"  ├── model.onnx       ({size_mb:.1f} MB)")
    print(f"  └── tokenizer.json")
    print(f"\nSet PLINY_MODEL_DIR={args.model_dir} to use embeddings.")
    print(f"Or copy to default location: ~/.pliny/models/")


if __name__ == "__main__":
    main()
