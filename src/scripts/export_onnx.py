"""Export all-MiniLM-L6-v2 to ONNX for faster inference + lower memory."""
from pathlib import Path

from optimum.onnxruntime import ORTModelForFeatureExtraction
from transformers import AutoTokenizer, AutoModel

model_id = "sentence-transformers/all-MiniLM-L6-v2"
output_dir = Path("models/onnx/all-MiniLM-L6-v2")
output_dir.mkdir(parents=True, exist_ok=True)

print(f"Exporting {model_id} to ONNX...")

# Load model and export to ONNX
model = ORTModelForFeatureExtraction.from_pretrained(model_id, export=True)
tokenizer = AutoTokenizer.from_pretrained(model_id)

# Save ONNX model + config + tokenizer
model.save_pretrained(str(output_dir))
tokenizer.save_pretrained(str(output_dir))

# Also save the original model config so sentence-transformers can find it
original = AutoModel.from_pretrained(model_id)
original.config.save_pretrained(str(output_dir))

print(f"Done. Files in {output_dir}:")
for f in sorted(output_dir.iterdir()):
    size = f.stat().st_size
    print(f"  {f.name:40s} {size / 1024:.1f} KB")
