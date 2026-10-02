"""Admin-endpoints voor de decision-scorer (services/decision_scorer.py).

Auth: sessie-cookie óf X-Stroom-Internal-Token (paden staan in
_INTERNAL_TOKEN_PATH_SUFFIXES in main.py), zodat ze ook vanaf de host met curl
te bedienen zijn.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel

from core.db import async_session_maker, get_async_session
from services import decision_scorer
from services.llm_service import LLMService

router = APIRouter()


class ProfileBody(BaseModel):
    text: str


@router.get("/admin/decision-profile")
async def get_decision_profile(session=Depends(get_async_session)):
    return {"profile": await decision_scorer.load_profile(session),
            "enabled": decision_scorer.ENABLED,
            "model": decision_scorer.DECISION_MODEL}


@router.put("/admin/decision-profile")
async def put_decision_profile(body: ProfileBody, session=Depends(get_async_session)):
    text = body.text.strip()
    if not 20 <= len(text) <= 4000:
        raise HTTPException(status_code=400, detail="profiel moet 20-4000 tekens zijn")
    return {"profile": await decision_scorer.save_profile(session, text, source="manual")}


@router.post("/admin/decision-profile/rebuild")
async def rebuild_decision_profile(request: Request, session=Depends(get_async_session)):
    """Overschrijft het profiel (ook een handmatig aangepast) met een nieuw
    automatisch profiel uit de gelikete lessen."""
    try:
        profile = await decision_scorer.build_profile(
            session, LLMService(request.app.state.llm_client))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"profile": profile}


@router.post("/admin/decision-score/run")
async def run_decision_score(request: Request, background_tasks: BackgroundTasks):
    if not decision_scorer.ENABLED:
        raise HTTPException(status_code=409, detail="SCORER_MODE is niet 'decision'")
    background_tasks.add_task(decision_scorer.run_batch, async_session_maker,
                              LLMService(request.app.state.llm_client))
    return {"started": True}


@router.get("/admin/decision-score/status")
async def decision_score_status():
    return {
        "enabled": decision_scorer.ENABLED,
        "mode": decision_scorer.SCORER_MODE,
        "model": decision_scorer.DECISION_MODEL,
        "url": decision_scorer.DECISION_URL,
        "interval_sec": decision_scorer.INTERVAL_SEC,
        "interest_weight": decision_scorer.INTEREST_WEIGHT,
        "max_age_days": decision_scorer.MAX_AGE_DAYS,
        **decision_scorer.state,
    }
