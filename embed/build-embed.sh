#!/usr/bin/env bash
# Host-veilige build van de stroom-embed image, zonder de host te OOM'en.
#
# De zware export + quantisatie draaien in GECAPTE wegwerp-containers; daarna
# een slanke `docker build` (geen torch). Idempotent — draai opnieuw bij een
# model- of code-wijziging. De cap (default 2800m, geen swap) houdt de host
# veilig: overschrijdt een stap 'm, dan kilt alleen die wegwerp-container
# zichzelf, niet de host.
#
# Op een krappe host (Strongbad = 3.7 GB): stop eerst tijdelijk wat non-core
# containers voor headroom, bv:
#   docker stop litellm netdata samenvat-agent
#   ./build-embed.sh
#   docker start litellm netdata samenvat-agent
#
# Deploy daarna met:  docker compose up -d --no-build stroom-embed
set -euo pipefail
cd "$(dirname "$0")"

IMAGE="${IMAGE:-vps-stacks-stroom-embed:latest}"
CAP="${CAP:-2800m}"
mkdir -p _artifacts

echo ">> [1/3] fp32 ONNX-export (gecapt $CAP, torch)"
docker run --rm --memory="$CAP" --memory-swap="$CAP" \
  -v "$PWD":/src:ro -v "$PWD/_artifacts":/model -w /src \
  python:3.12-slim sh -c "set -e; \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu; \
    pip install --no-cache-dir -r requirements-export.txt; \
    python export_model.py"

echo ">> [2/3] int8-quantisatie (gecapt $CAP, onnxruntime, geen torch)"
docker run --rm --memory="$CAP" --memory-swap="$CAP" \
  -v "$PWD":/src:ro -v "$PWD/_artifacts":/model -w /src \
  python:3.12-slim sh -c "set -e; \
    pip install --no-cache-dir onnxruntime onnx; \
    python quantize_model.py"

echo ">> [3/3] slanke runtime-image (geen torch)"
rm -f _artifacts/model.onnx   # 470 MB fp32 hoeft niet in de image
docker build -t "$IMAGE" .

echo ">> klaar: $IMAGE"
docker images "$IMAGE" --format "{{.Repository}}:{{.Tag}} {{.Size}}"
