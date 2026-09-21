"""Talking to the model, with the failures that actually happen handled.

Three of them, learned rather than anticipated:

Structured output is not reliable. The provider's JSON mode intermittently
rejects generations that are in fact valid JSON, and a pipeline that dies
because a wrapper had an opinion about its own output is not acceptable at this
layer. Every structured call re-parses the raw content as a fallback.

Rate limits are the normal case on a free tier, not an exception. A 429 carries
a retry-after and honouring it is the difference between finishing and burning
the day's budget on retries.

Token spend has to be attributable. A run that costs money without saying where
it went cannot be reasoned about, so usage accumulates in a ContextVar for the
duration of one analysis and is persisted with it.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

from app.config import settings

log = logging.getLogger("llm")

CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

# Published Groq rates, per million tokens. Used to report what a run cost;
# an unknown model contributes nothing rather than a guess.
_RATES = {
    "openai/gpt-oss-20b": (0.10, 0.50),
    "openai/gpt-oss-120b": (0.15, 0.75),
}


@dataclass
class Ledger:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    by_model: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def cost_usd(self) -> float:
        total = 0.0
        for model, tokens in self.by_model.items():
            rate = _RATES.get(model)
            if rate is None:
                continue
            # Split at the observed ratio rather than assuming: prompts dominate
            # here, and pricing input as output would overstate by ~4x.
            share = tokens / max(1, self.total)
            total += (self.prompt_tokens * share * rate[0]
                      + self.completion_tokens * share * rate[1]) / 1_000_000
        return round(total, 6)


_ledger: contextvars.ContextVar[Ledger | None] = contextvars.ContextVar(
    "llm_ledger", default=None)


@contextlib.contextmanager
def ledger():
    """Account for everything spent inside the block."""
    book = Ledger()
    token = _ledger.set(book)
    try:
        yield book
    finally:
        _ledger.reset(token)


class LLMError(RuntimeError):
    pass


def _record(model: str, usage: dict) -> None:
    book = _ledger.get()
    if book is None or not usage:
        return
    book.calls += 1
    book.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
    book.completion_tokens += int(usage.get("completion_tokens", 0) or 0)
    book.by_model[model] = (book.by_model.get(model, 0)
                            + int(usage.get("total_tokens", 0) or 0))


def complete(system: str, user: str, *, model: str | None = None,
             temperature: float = 0.2, max_tokens: int = 2048,
             json_mode: bool = False, attempts: int = 4) -> str:
    """One chat completion, retried on the failures that resolve with time."""
    model = model or settings().model_fast
    body = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.post(
                CHAT_URL,
                headers={"Authorization": f"Bearer {settings().groq_api_key}"},
                json=body, timeout=httpx.Timeout(180.0, connect=20.0),
            )
        except httpx.HTTPError as exc:
            last = LLMError(f"could not reach the model: {exc}")
            time.sleep(min(30, 2 ** attempt))
            continue

        if resp.status_code == 429:
            wait = _retry_after(resp) or min(60, 5 * 2 ** attempt)
            log.warning("[llm] rate limited, waiting %.1fs (attempt %d/%d)",
                        wait, attempt, attempts)
            last = LLMError(f"rate limited: {resp.text[:200]}")
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            last = LLMError(f"provider error {resp.status_code}")
            time.sleep(min(30, 2 ** attempt))
            continue

        if resp.status_code >= 400:
            # A 4xx that is not a rate limit will not get better by repeating.
            raise LLMError(f"{resp.status_code}: {resp.text[:300]}")

        payload = resp.json()
        _record(model, payload.get("usage") or {})
        choices = payload.get("choices") or []
        if not choices:
            raise LLMError("the model returned no choices")
        return choices[0]["message"]["content"] or ""

    raise last or LLMError("exhausted attempts")


def complete_json(system: str, user: str, *, model: str | None = None,
                  temperature: float = 0.0, max_tokens: int = 4096) -> dict:
    """A completion that must be JSON, with a fallback for when it is not.

    Asking for JSON mode and then re-parsing anyway looks redundant and is not:
    the wrapper rejects its own valid generations often enough that a pipeline
    depending on it alone fails for no reason the user can act on.
    """
    raw = complete(system, user, model=model, temperature=temperature,
                   max_tokens=max_tokens, json_mode=True)
    parsed = _loads(raw)
    if parsed is not None:
        return parsed

    log.warning("[llm] JSON mode returned unparseable output, retrying plain")
    raw = complete(system + "\n\nReply with JSON and nothing else.", user,
                   model=model, temperature=temperature, max_tokens=max_tokens)
    parsed = _loads(raw)
    if parsed is None:
        raise LLMError(f"could not parse a JSON object from: {raw[:300]}")
    return parsed


def _loads(raw: str) -> dict | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {"items": value}
    except json.JSONDecodeError:
        pass
    # Models wrap JSON in prose or a fence more often than they emit bare JSON.
    fenced = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    if fenced:
        try:
            value = json.loads(fenced.group(1).strip())
            return value if isinstance(value, dict) else {"items": value}
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{.*\}", raw, re.S)
    if brace:
        try:
            value = json.loads(brace.group(0))
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _retry_after(resp: httpx.Response) -> float | None:
    header = resp.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    m = re.search(r"try again in ([\d.]+)s", resp.text or "", re.I)
    return float(m.group(1)) if m else None
