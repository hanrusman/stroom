def auto_score_guard(alias: str = "") -> str:
    """SQL-conditie: de huidige score is van het systeem en mag overschreven
    worden. Dat is reason 'auto' (worker/backfill/decision-batch), of nooit
    gescoord: reason én updated_at NULL. De PATCH /quality-score zet altijd
    updated_at, óók als de caller geen reason meegeeft — zo'n handmatige score
    (of handmatige neutrale NULL) is ground truth en blijft staan."""
    p = f"{alias}." if alias else ""
    return (f"({p}quality_score_reason = 'auto' OR "
            f"({p}quality_score_reason IS NULL AND {p}quality_score_updated_at IS NULL))")
