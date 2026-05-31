from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from core.db import get_async_session


router = APIRouter()


class TranscriptSummary(BaseModel):
    id: str
    title: str
    author: Optional[str]
    source_name: str
    duration_seconds: Optional[int]
    published_at: Optional[str]
    transcript_chars: int
    has_summary: bool


class TranscriptDetail(BaseModel):
    id: str
    title: str
    description: Optional[str]
    author: Optional[str]
    source_name: str
    media_url: Optional[str]
    thumbnail_url: Optional[str]
    duration_seconds: Optional[int]
    published_at: Optional[str]
    created_at: str
    transcript: str
    summary: Optional[str]
    summary_model: Optional[str]
    summary_generated_at: Optional[str]


class TranscriptSnippet(BaseModel):
    text: str
    start_s: Optional[float] = None  # seconds from start, if from segment
    end_s: Optional[float] = None


class TranscriptSearchHit(BaseModel):
    id: str
    title: str
    source_name: str
    published_at: Optional[str]
    media_url: Optional[str]
    summary: Optional[str]
    snippets: List[TranscriptSnippet]


_STOPWORDS = {
    "de", "het", "een", "en", "of", "in", "op", "aan", "te", "van", "voor",
    "met", "is", "zijn", "wat", "wie", "hoe", "waar", "die", "dat", "deze",
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "what", "who", "how", "where", "that", "this",
}


def _query_terms(query: str) -> List[str]:
    """Split query into significant lowercase terms (≥3 chars, no stopwords)."""
    terms = []
    for w in query.lower().split():
        w = "".join(c for c in w if c.isalnum())
        if len(w) >= 3 and w not in _STOPWORDS:
            terms.append(w)
    return terms or [query.strip().lower()]


def _extract_snippets(
    transcript: Optional[str],
    segments: Optional[list],
    query: str,
    max_snippets: int = 3,
) -> List[TranscriptSnippet]:
    """Vind tot `max_snippets` fragmenten die zo veel mogelijk van de
    significante query-woorden bevatten. Voorkeur voor `transcript_segments`
    (timestamped) als die er zijn; anders substring-extractie rond de
    longest matching term.
    """
    terms = _query_terms(query)
    if not terms:
        return []

    # 1) Score segments by how many distinct terms they contain.
    if segments:
        scored = []
        for seg in segments:
            text = (seg or {}).get("text") or ""
            lower = text.lower()
            hits = sum(1 for t in terms if t in lower)
            if hits:
                scored.append((hits, seg, text))
        # Sort: most-matching first, ties broken by earliest start.
        scored.sort(key=lambda s: (-s[0], (s[1] or {}).get("start") or 0))
        out: List[TranscriptSnippet] = []
        for _, seg, text in scored[:max_snippets]:
            out.append(TranscriptSnippet(
                text=text.strip(),
                start_s=seg.get("start"),
                end_s=seg.get("end"),
            ))
        if out:
            return out

    # 2) Fallback: substring-extractie op de volle transcript. Pak de longest
    # term (meest specifieke) en zoek alle voorkomens.
    text = transcript or ""
    if not text:
        return []
    primary = max(terms, key=len)
    lower = text.lower()
    out2: List[TranscriptSnippet] = []
    pos = 0
    while len(out2) < max_snippets:
        idx = lower.find(primary, pos)
        if idx < 0:
            break
        start = max(0, idx - 120)
        end = min(len(text), idx + len(primary) + 200)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = "…" + snippet
        if end < len(text):
            snippet = snippet + "…"
        out2.append(TranscriptSnippet(text=snippet))
        pos = end
    return out2


# Raw SQL met expliciete kolommen + ::text casts. Stroom's Item-model heeft
# een bekende enum-deserialisatie-bug (ContentKind: DB-waarde 'rss', enum-
# member 'RSS') die `select(Item)` doet falen — daarom raw SQL net als
# main.py:list_filtered_items (huygens-route).


@router.get("/transcripts", response_model=List[TranscriptSummary])
async def list_transcripts(
    search: Optional[str] = Query(None, description="Substring filter op title (ILIKE)."),
    source: Optional[str] = Query(None, description="Substring filter op source name (ILIKE)."),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    include_archived: bool = Query(False),
    session=Depends(get_async_session),
):
    """List items with a non-empty transcript (internal corpus consumer)."""
    clauses = ["i.transcript IS NOT NULL", "i.transcript <> ''"]
    params: dict = {"lim": limit, "off": offset}
    if search:
        clauses.append("i.title ILIKE :search")
        params["search"] = f"%{search}%"
    if source:
        clauses.append("s.name ILIKE :source")
        params["source"] = f"%{source}%"
    if not include_archived:
        clauses.append("i.status <> 'archived'::item_status")

    sql = f"""
        SELECT i.id::text AS id,
               i.title,
               i.author,
               s.name AS source_name,
               i.duration_seconds,
               i.published_at,
               LENGTH(i.transcript) AS transcript_chars,
               (i.summary IS NOT NULL AND i.summary <> '') AS has_summary
        FROM items i
        JOIN sources s ON s.id = i.source_id
        WHERE {" AND ".join(clauses)}
        ORDER BY COALESCE(i.published_at, i.created_at) DESC
        LIMIT :lim OFFSET :off
    """
    rows = (await session.exec(sa_text(sql).bindparams(**params))).all()
    return [
        TranscriptSummary(
            id=r[0],
            title=r[1],
            author=r[2],
            source_name=r[3],
            duration_seconds=r[4],
            published_at=r[5].isoformat() if r[5] else None,
            transcript_chars=int(r[6]),
            has_summary=bool(r[7]),
        )
        for r in rows
    ]


@router.get("/internal/transcripts/search", response_model=List[TranscriptSearchHit])
async def search_transcripts(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(5, ge=1, le=20),
    session=Depends(get_async_session),
):
    """Machine-to-machine FTS over transcript-corpus, met snippet-extractie.

    Gebruikt de bestaande `search_tsv` GIN-index (gegenereerde kolom over
    title+summary+transcript+description). Per hit max 3 snippets — bij
    voorkeur timestamped segments, anders ±120 chars context rond elke match.

    Auth via internal-token middleware (prefix `/internal/`). Intended for
    machine-to-machine consumers that need to grep the transcript corpus.
    """
    sql = sa_text("""
        SELECT i.id::text,
               i.title,
               s.name AS source_name,
               i.published_at,
               i.media_url,
               i.summary,
               i.transcript,
               i.transcript_segments,
               ts_rank(i.search_tsv, plainto_tsquery('simple', :q)) AS rank
        FROM items i
        JOIN sources s ON s.id = i.source_id
        WHERE i.transcript IS NOT NULL
          AND i.transcript <> ''
          AND i.search_tsv @@ plainto_tsquery('simple', :q)
        ORDER BY rank DESC, i.published_at DESC NULLS LAST
        LIMIT :lim
    """).bindparams(q=q, lim=limit)
    rows = (await session.exec(sql)).all()

    hits: List[TranscriptSearchHit] = []
    for r in rows:
        snippets = _extract_snippets(r[6], r[7], q)
        if not snippets:
            # Match was alleen op title/summary/description — fallback naar
            # de eerste 240 chars van de transcript zodat de LLM tóch context heeft.
            head = (r[6] or "")[:240].strip()
            if head:
                snippets = [TranscriptSnippet(text=head + "…")]
        # Truncate summary to a teaser; full summary is fetchable via
        # GET /transcripts/{id}. Otherwise response can balloon to >100 KB
        # for a single search hit (Stroom-summaries can be 30-70 KB markdown).
        full_summary = r[5] or ""
        summary_teaser = full_summary[:240].rstrip() + "…" if len(full_summary) > 240 else (full_summary or None)
        hits.append(TranscriptSearchHit(
            id=r[0],
            title=r[1],
            source_name=r[2],
            published_at=r[3].isoformat() if r[3] else None,
            media_url=r[4],
            summary=summary_teaser,
            snippets=snippets,
        ))
    return hits


@router.get("/transcripts/{item_id}", response_model=TranscriptDetail)
async def get_transcript_detail(
    item_id: str,
    session=Depends(get_async_session),
):
    """Volledige transcript + metadata voor één item."""
    try:
        uid = UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid item ID format")

    sql = sa_text("""
        SELECT i.id::text AS id,
               i.title,
               i.description,
               i.author,
               s.name AS source_name,
               i.media_url,
               i.thumbnail_url,
               i.duration_seconds,
               i.published_at,
               i.created_at,
               i.transcript,
               i.summary,
               i.summary_model,
               i.summary_generated_at
        FROM items i
        JOIN sources s ON s.id = i.source_id
        WHERE i.id = :uid
    """).bindparams(uid=uid)
    row = (await session.exec(sql)).first()

    if not row:
        raise HTTPException(status_code=404, detail="Item not found")

    transcript = row[10] or ""
    if not transcript.strip():
        raise HTTPException(status_code=404, detail="Transcript not available")

    return TranscriptDetail(
        id=row[0],
        title=row[1],
        description=row[2],
        author=row[3],
        source_name=row[4],
        media_url=row[5],
        thumbnail_url=row[6],
        duration_seconds=row[7],
        published_at=row[8].isoformat() if row[8] else None,
        created_at=row[9].isoformat(),
        transcript=transcript,
        summary=row[11],
        summary_model=row[12],
        summary_generated_at=row[13].isoformat() if row[13] else None,
    )
