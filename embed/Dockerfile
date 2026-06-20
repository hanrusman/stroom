# syntax=docker/dockerfile:1
# Canonieke build: slank, GEEN torch. Kopieert het vooraf-gequantizeerde
# int8-model uit _artifacts/ (gegenereerd door build-embed.sh, gitignored).
#
# Waarom niet torch-at-build: de export/quantisatie piekt >2.8 GB en OOM't
# kleine hosts (Strongbad = 3.7 GB). Zie build-embed.sh + Dockerfile.model-export.
#
# Op een verse clone zonder _artifacts/ faalt deze build SCHOON op de COPY
# (geen OOM) — draai eerst `./build-embed.sh`.
FROM python:3.12-slim

WORKDIR /app
ENV OMP_NUM_THREADS=1 \
    ONNXRUNTIME_INTRA_OP_NUM_THREADS=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN adduser --disabled-password --gecos '' appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Vooraf gebouwd door build-embed.sh (off-build, gecapt). Niet in git (gitignored);
# back-up als GitHub-release-asset. tokenizer.json hoort bij model_quantized.onnx.
COPY _artifacts/model_quantized.onnx /model/model_quantized.onnx
COPY _artifacts/tokenizer.json /model/tokenizer.json
COPY app.py .

RUN chown -R appuser:appuser /app /model
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
