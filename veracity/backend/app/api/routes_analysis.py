"""Requesting an analysis, and reading it back."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.auth import Principal, current_principal
from app.api.schemas import timecode
from app.db.models import (Analysis, AnalysisMode, AnalysisState, Claim,
                           MediaItem, MediaState)
from app.db.session import app_session, owner_session
from app.jobs import queue
from app.quota import CREDITS, QuotaExceeded, consume

log = logging.getLogger("api.analysis")
router = APIRouter(prefix="/api/media/{media_id}/analysis", tags=["analysis"])


class AnalysisRequest(BaseModel):
    mode: AnalysisMode = AnalysisMode.summary


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def request_analysis(media_id: str, body: AnalysisRequest,
                           principal: Principal = Depends(current_principal)):
    with app_session(principal.user_id) as session:
        media = session.get(MediaItem, media_id)
        if media is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such media")
        if media.state != MediaState.ready:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"this media is {media.state.value}; it has to finish "
                f"transcribing before it can be analysed",
            )

        # One analysis per mode per item. Re-requesting the same depth returns
        # what already exists rather than paying for it twice.
        existing = (session.query(Analysis)
                    .filter_by(media_id=media_id, mode=body.mode)
                    .filter(Analysis.state != AnalysisState.failed)
                    .first())
        if existing is not None:
            return {"id": existing.id, "state": existing.state.value,
                    "mode": existing.mode.value, "reused": True}

        # Priced by depth, not by run: report searches for and judges every
        # claim separately and costs roughly fifteen times a summary.
        try:
            consume(session, principal.user_id, meter="analysis_credits",
                    amount=CREDITS[body.mode])
        except QuotaExceeded as exc:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc))

        analysis = Analysis(media_id=media_id, user_id=principal.user_id,
                            mode=body.mode, state=AnalysisState.queued)
        session.add(analysis)
        session.flush()
        analysis_id = analysis.id

    with owner_session() as session:
        # Report depth is many searches and many judgements; run it behind the
        # cheaper depths rather than ahead of them.
        queue.enqueue(session, "analyze", {"analysis_id": analysis_id},
                      priority=200 if body.mode == AnalysisMode.report else 150)
    return {"id": analysis_id, "state": "queued", "mode": body.mode.value,
            "reused": False}


@router.get("")
def list_analyses(media_id: str,
                        principal: Principal = Depends(current_principal)):
    with app_session(principal.user_id) as session:
        if session.get(MediaItem, media_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such media")
        rows = (session.query(Analysis).filter_by(media_id=media_id)
                .order_by(Analysis.created_at.desc()).all())
        return {"items": [{"id": a.id, "mode": a.mode.value,
                           "state": a.state.value,
                           "confidence": a.overall_confidence,
                           "created_at": a.created_at} for a in rows]}


@router.get("/{analysis_id}")
def get_analysis(media_id: str, analysis_id: str,
                       principal: Principal = Depends(current_principal)):
    with app_session(principal.user_id) as session:
        analysis = session.get(Analysis, analysis_id)
        if analysis is None or analysis.media_id != media_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such analysis")

        claims = (session.query(Claim).filter_by(analysis_id=analysis_id)
                  .order_by(Claim.ordinal).all())
        return {
            "id": analysis.id,
            "media_id": media_id,
            "mode": analysis.mode.value,
            "state": analysis.state.value,
            "error": analysis.error,
            "summary": analysis.summary_md,
            "key_points": _timed(analysis.key_points),
            "topics": _timed(analysis.topics),
            "overall_confidence": analysis.overall_confidence,
            "confidence_factors": analysis.confidence_factors,
            "perspectives": _timed(analysis.perspectives),
            "tokens_used": analysis.tokens_used,
            "cost_usd": analysis.cost_usd,
            "claims": [{
                "ordinal": c.ordinal,
                "at": timecode(c.start_ms),
                "start_ms": c.start_ms,
                "end_ms": c.end_ms,
                "spoken": c.spoken_text,
                "proposition": c.proposition,
                "verdict": c.verdict.value,
                "verdict_confidence": c.verdict_confidence,
                "asr_confidence": c.asr_confidence,
                "reasoning": c.reasoning,
                "independently_corroborated": c.independently_corroborated,
                "evidence": c.evidence or [],
            } for c in claims],
        }


def _timed(rows):
    """Add a human timecode wherever a row carries a millisecond offset."""
    if not rows:
        return []
    out = []
    for r in rows:
        if isinstance(r, dict):
            r = dict(r)
            if isinstance(r.get("start_ms"), int):
                r["at"] = timecode(r["start_ms"])
            out.append(r)
    return out
