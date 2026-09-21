"""Finding evidence about a claim, from sources the speaker did not choose.

Deliberately thin. The only thing worth saying about it is that results are
searched for *per claim*, not once for the media as a whole: evidence retrieved
for "the reef is the largest coral system" tells you nothing about "it can be
seen from space", and scoring the second against the first is how a verifier
ends up measuring topical similarity while calling it support.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

log = logging.getLogger("analysis.search")

TAVILY_URL = "https://api.tavily.com/search"


@dataclass(frozen=True)
class Evidence:
    title: str
    url: str
    snippet: str
    score: float | None = None

    def as_dict(self) -> dict:
        return {"title": self.title, "url": self.url,
                "snippet": self.snippet, "score": self.score}


class SearchUnavailable(RuntimeError):
    """No search backend is configured. Verification cannot run."""


def available() -> bool:
    return bool(os.getenv("TAVILY_API_KEY"))


def search(query: str, *, limit: int = 5,
           timeout: float = 30.0) -> list[Evidence]:
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        raise SearchUnavailable(
            "TAVILY_API_KEY is not set, so claims cannot be checked against "
            "independent sources. Summary and deep analysis still work."
        )
    try:
        resp = httpx.post(TAVILY_URL, json={
            "api_key": key,
            "query": query[:380],
            "max_results": limit,
            "search_depth": "basic",
            "include_answer": False,
        }, timeout=timeout)
    except httpx.HTTPError as exc:
        log.warning("[search] %s", exc)
        return []

    if resp.status_code >= 400:
        log.warning("[search] %s: %s", resp.status_code, resp.text[:160])
        return []

    out: list[Evidence] = []
    for r in (resp.json().get("results") or [])[:limit]:
        url = (r.get("url") or "").strip()
        if not url:
            continue
        out.append(Evidence(
            title=(r.get("title") or url)[:300],
            url=url,
            snippet=" ".join((r.get("content") or "").split())[:1200],
            score=r.get("score"),
        ))
    return out
