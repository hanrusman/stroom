"""Quantize model.onnx -> model_quantized.onnx (dynamische int8).

Alleen onnxruntime (geen torch) — veel lichter dan optimum's ORTQuantizer, die
op een 3.7 GB host OOM'de. Past ruim in een 2800m-gecapte container.
"""
import os

from onnxruntime.quantization import QuantType, quantize_dynamic

MODEL_DIR = os.environ.get("EXPORT_PATH", "/model")


def main() -> None:
    src = os.path.join(MODEL_DIR, "model.onnx")
    dst = os.path.join(MODEL_DIR, "model_quantized.onnx")
    print(f"Quantizing {src} -> {dst} (int8)...", flush=True)
    quantize_dynamic(src, dst, weight_type=QuantType.QInt8)
    print(f"Done: {dst} ({os.path.getsize(dst) // (1024 * 1024)} MB)", flush=True)


if __name__ == "__main__":
    main()
