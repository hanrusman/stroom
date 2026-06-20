"""Build-time: exporteer multilingual-e5-small naar ONNX + dynamische int8.

Draait in de Docker builder-stage (heeft torch/transformers/optimum + internet).
Schrijft model_quantized.onnx + tokenizer.json naar /model; de runtime-image
kopieert alleen die map en heeft torch dus niet nodig.
"""
import os

from optimum.onnxruntime import ORTModelForFeatureExtraction, ORTQuantizer
from optimum.onnxruntime.configuration import AutoQuantizationConfig
from transformers import AutoTokenizer

MODEL_NAME = "intfloat/multilingual-e5-small"
EXPORT_PATH = "/model"


def export_and_quantize() -> None:
    os.makedirs(EXPORT_PATH, exist_ok=True)

    print("Exporting model to ONNX...", flush=True)
    model = ORTModelForFeatureExtraction.from_pretrained(MODEL_NAME, export=True)
    model.save_pretrained(EXPORT_PATH)
    AutoTokenizer.from_pretrained(MODEL_NAME).save_pretrained(EXPORT_PATH)
    print("Base ONNX model + tokenizer saved.", flush=True)

    # Dynamische int8-quantisatie (geen calibratie-set nodig).
    quantizer = ORTQuantizer.from_pretrained(EXPORT_PATH, file_name="model.onnx")
    try:
        qconfig = AutoQuantizationConfig.avx512_vnni(is_static=False, per_channel=False)
        print("Quantization config: avx512_vnni", flush=True)
    except Exception:
        qconfig = AutoQuantizationConfig.avx2(is_static=False, per_channel=False)
        print("Quantization config: avx2 (vnni unavailable)", flush=True)

    quantizer.quantize(
        save_dir=EXPORT_PATH,
        quantization_config=qconfig,
        file_suffix="quantized",  # -> model_quantized.onnx
    )
    print("Quantized model written to /model/model_quantized.onnx", flush=True)
    print("Contents of /model:", sorted(os.listdir(EXPORT_PATH)), flush=True)


if __name__ == "__main__":
    export_and_quantize()
