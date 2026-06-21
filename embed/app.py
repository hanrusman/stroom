"""stroom-embed — minimale ONNX-int8 embeddings-microservice (e5-small).

Bewust simpel en geïsoleerd: geen torch, alleen onnxruntime + tokenizers.
score_interest in stroom-api roept /embed aan; bij elke fout daar fail-open
naar None. Deze service hoeft dus niet defensief te zijn richting de caller —
hij moet vooral binnen zijn cgroup-cap (512m) blijven en niet hangen.
"""
import logging
from typing import List

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from tokenizers import Tokenizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stroom-embed")

MODEL_PATH = "/model/model_quantized.onnx"
TOKENIZER_PATH = "/model/tokenizer.json"
MAX_BATCH = 64
MAX_LEN = 512

app = FastAPI(title="stroom-embed")

session: ort.InferenceSession | None = None
tokenizer: Tokenizer | None = None
input_names: set[str] = set()


class EmbedRequest(BaseModel):
    texts: List[str] = Field(..., min_length=1, max_length=MAX_BATCH)
    prefix: str = "query"


@app.on_event("startup")
def load_model() -> None:
    global session, tokenizer, input_names
    try:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        # Schakel de CPU-memory-arena uit: die groeit mee met de grootste request
        # ooit en krimpt niet, waardoor het resident-geheugen richting de 768m-cap
        # kroop (~742 MB high-water). Zonder arena blijft het vlak rond ~250-300 MB,
        # tegen verwaarloosbaar perf-verlies bij onze lage QPS. Dat geeft de host
        # weer marge zodat de transcribe mem-gate (500 MB) minder vaak blokkeert.
        opts.enable_cpu_mem_arena = False
        session = ort.InferenceSession(
            MODEL_PATH, sess_options=opts, providers=["CPUExecutionProvider"]
        )
        input_names = {i.name for i in session.get_inputs()}
        tokenizer = Tokenizer.from_file(TOKENIZER_PATH)
        tokenizer.enable_truncation(max_length=MAX_LEN)
        tokenizer.enable_padding()
        logger.info(
            "model loaded; inputs=%s dim=%s",
            sorted(input_names), session.get_outputs()[0].shape[-1],
        )
    except Exception as e:  # fail naar een duidelijk-unhealthy state
        logger.error("failed to load model: %s", e)
        session = None
        tokenizer = None


@app.get("/health")
def health():
    if session is not None and tokenizer is not None:
        return {"status": "ok", "model_loaded": True}
    return JSONResponse(status_code=503, content={"status": "error", "model_loaded": False})


@app.post("/embed")
def embed(req: EmbedRequest):
    if session is None or tokenizer is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    if req.prefix not in ("query", "passage"):
        raise HTTPException(status_code=400, detail="prefix must be 'query' or 'passage'")

    encodings = tokenizer.encode_batch([f"{req.prefix}: {t}" for t in req.texts])
    input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
    attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)

    feed = {"input_ids": input_ids, "attention_mask": attention_mask}
    if "token_type_ids" in input_names:
        feed["token_type_ids"] = np.array([e.type_ids for e in encodings], dtype=np.int64)

    token_embeddings = session.run(None, feed)[0]  # (batch, seq_len, dim)

    # Mean pooling gewogen met de attention-mask (NIET [CLS]) — e5-conventie.
    mask = np.expand_dims(attention_mask, -1).astype(np.float32)
    summed = np.sum(token_embeddings * mask, axis=1)
    counts = np.clip(mask.sum(axis=1), a_min=1e-9, a_max=None)
    pooled = summed / counts

    # L2-normaliseer zodat dot-product met de centroid == cosine-similarity.
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1e-12, norms)
    normalized = (pooled / norms).astype(np.float32)

    return {"vectors": normalized.tolist(), "dim": int(normalized.shape[1])}
