"""Asking a question of one piece of media.

The answer is written only from passages retrieved out of that transcript, and
every sentence carries the timestamp it came from. Declining is a first-class
outcome: a transcript that does not contain the answer should produce a refusal,
not a fluent paragraph assembled from the nearest topically-similar passages.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.auth import Principal, current_principal
from app.api.schemas import timecode
from app.config import settings
from app.db.models import MediaItem, MediaState
from app.db.session import app_session
from app.llm import complete_json

log = logging.getLogger("api.ask")
router = APIRouter(prefix="/api/media/{media_id}/ask", tags=["ask"])

SYSTEM = """You answer a question using only the excerpts given to you.

The excerpts are passages from a transcript, each prefixed with the time it was \
spoken at.

Rules:
- Answer only from the excerpts. Do not use anything you know independently.
- Cite the timestamp of every excerpt you relied on.
- If the excerpts do not answer the question, say so plainly and say what is \
missing. A refusal is a correct answer and is preferred to a plausible one \
assembled from passages that are merely on the same topic.
- Do not speculate about what the speaker probably meant.

Return JSON:
{"answered": true|false,
 "answer": "<your answer, or what is missing>",
 "used": [<start_ms of each excerpt you relied on>]}"""


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


@router.post("")
async def ask(media_id: str, body: Question,
              principal: Principal = Depends(current_principal)):
    with app_session(principal.user_id) as session:
        media = session.get(MediaItem, media_id)
        if media is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such media")
        if media.state != MediaState.ready:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"this media is {media.state.value}, not ready",
            )

        from app.analysis.retrieve import retrieve
        passages = retrieve(session, media_id, body.question)

        if not passages:
            return {
                "answered": False,
                "answer": "Nothing in this transcript bears on that question.",
                "passages": [],
            }

        excerpts = "\n\n".join(
            f"[{timecode(p['start_ms'])}] {p['text']}" for p in passages
        )
        payload = complete_json(
            SYSTEM,
            f"Question: {body.question}\n\nExcerpts:\n\n{excerpts}",
            model=settings().model_smart,
        )

        used = set(payload.get("used") or [])
        return {
            "answered": bool(payload.get("answered")),
            "answer": (payload.get("answer") or "").strip(),
            "passages": [{
                "at": timecode(p["start_ms"]),
                "start_ms": p["start_ms"],
                "end_ms": p["end_ms"],
                "text": p["text"],
                "used": p["start_ms"] in used,
            } for p in passages],
        }
