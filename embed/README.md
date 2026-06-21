# stroom-embed

Geïsoleerde embeddings-microservice voor Stroom's interest-scoring. ONNX-int8
`intfloat/multilingual-e5-small` via onnxruntime + tokenizers (geen torch op
runtime). `stroom-api` roept `POST /embed` aan en faalt fail-open naar `None`.

## Bouwen — gebruik `./build-embed.sh`

⚠️ **Bouw NIET met een torch-export op een kleine host.** De export +
quantisatie piekt >2.8 GB en OOM't een 3.7 GB host (Strongbad). `build-embed.sh`
draait die stappen in **gecapte wegwerp-containers** (default `CAP=2800m`, geen
swap), zodat de host nooit omver gaat — een te grote stap kilt alleen zichzelf.

```bash
# op een krappe host: maak eerst headroom vrij
docker stop litellm netdata samenvat-agent
./build-embed.sh
docker start litellm netdata samenvat-agent

# deploy (gebruikt de getagde image, bouwt niet opnieuw):
docker compose up -d --no-build stroom-embed
```

Het script doet: (1) fp32 ONNX-export (torch), (2) int8-quantisatie via
`quantize_dynamic` (alleen onnxruntime — veel lichter dan optimum's quantizer),
(3) slanke `docker build` met de canonieke `Dockerfile` (kopieert het artefact).

## Bestanden

| Bestand | Rol |
|---|---|
| `Dockerfile` | **canoniek**, slank — kopieert `_artifacts/model_quantized.onnx`. Geen torch. |
| `Dockerfile.model-export` | referentie: torch-export → int8 → runtime in één multi-stage build. Alleen op een ruime machine. Staat bewust niet in compose. |
| `build-embed.sh` | host-veilige build-orchestratie (gecapt, off-build). |
| `export_model.py` | fp32 ONNX-export (torch). |
| `quantize_model.py` | int8-quantisatie (onnxruntime, geen torch). |
| `app.py` | de FastAPI-service (mean-pooling + L2-norm; adaptieve ONNX-inputs). |
| `requirements.txt` | runtime-deps (geen torch). |
| `requirements-export.txt` | build-time deps, gepind voor reproduceerbaarheid. |
| `_artifacts/` | gegenereerde modelartefacten — **gitignored**; back-up als release-asset. |

## Caps (vps-stacks compose)

`memory: 768m` (onnxruntime-arena + int8-model ≈ 480 MB working set), `cpus: 1.0`,
`read_only`, intern `stroom-backend` netwerk, healthcheck + `restart: unless-stopped`.
