"""Exporteer multilingual-e5-small naar fp32 ONNX (model.onnx + tokenizer.json).

Heeft torch + optimum nodig (zwaar — draai gecapt via build-embed.sh of in de
builder-stage van Dockerfile.model-export, NIET zomaar op een kleine host).
De int8-quantisatie is een aparte, veel lichtere stap: zie quantize_model.py.
"""
import os

from optimum.onnxruntime import ORTModelForFeatureExtraction
from transformers import AutoTokenizer

MODEL_NAME = "intfloat/multilingual-e5-small"
EXPORT_PATH = os.environ.get("EXPORT_PATH", "/model")


def main() -> None:
    os.makedirs(EXPORT_PATH, exist_ok=True)
    print("Exporting model to ONNX...", flush=True)
    model = ORTModelForFeatureExtraction.from_pretrained(MODEL_NAME, export=True)
    model.save_pretrained(EXPORT_PATH)
    AutoTokenizer.from_pretrained(MODEL_NAME).save_pretrained(EXPORT_PATH)
    print(f"Wrote model.onnx + tokenizer.json to {EXPORT_PATH}", flush=True)
    print("Contents:", sorted(os.listdir(EXPORT_PATH)), flush=True)


if __name__ == "__main__":
    main()
