from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import contextvars
import re
import time
import logging

from langchain_core.language_models.chat_models import BaseChatModel

from config import get_settings

logger = logging.getLogger(__name__)


# =============================================
# Token accounting
# =============================================
#
# ResearchState.cost_tracking existed from the start and no node ever wrote to
# it, so "what does one deep research run cost?" — the question that decides
# whether the $20 Pro tier has a margin — had no answer.
#
# invoke_with_retry is the single chokepoint every LLM call passes through, so
# usage is recorded here rather than in nine separate agents. A ContextVar
# rather than a module global: concurrent research runs each need their own
# tally, and ContextVars propagate correctly across asyncio tasks.

_token_ledger: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "token_ledger", default=None
)


def new_token_ledger() -> dict:
    """Start a fresh tally for one research run and make it current."""
    ledger = {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0, "calls": 0, "by_model": {}}
    _token_ledger.set(ledger)
    return ledger


def current_token_ledger() -> dict | None:
    return _token_ledger.get()


def _record_usage(response, model: str | None) -> None:
    """Pull token counts off a LangChain response, if it carried any.

    Providers expose this inconsistently and some responses have none at all,
    so a missing count is normal and must never break the call it is measuring.
    """
    ledger = _token_ledger.get()
    if ledger is None:
        return

    usage = getattr(response, "usage_metadata", None) or {}
    if not usage:
        meta = getattr(response, "response_metadata", None) or {}
        usage = meta.get("token_usage") or meta.get("usage") or {}

    if not isinstance(usage, dict):
        return

    inp = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    out = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or (inp + out))
    if not total:
        return

    ledger["calls"] += 1
    ledger["input_tokens"] += inp
    ledger["output_tokens"] += out
    ledger["total_tokens"] += total

    key = model or "unknown"
    per_model = ledger["by_model"].setdefault(key, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    per_model["calls"] += 1
    per_model["input_tokens"] += inp
    per_model["output_tokens"] += out


def estimate_cost_usd(ledger: dict) -> float:
    """Estimate spend from the measured token counts.

    The token counts are exact; this number is not. Rates come from settings so
    they can be corrected without a code change — check them against current
    Groq pricing before quoting the result to anyone.
    """
    settings = get_settings()
    rates = {
        settings.groq_model_smart: (settings.price_smart_input_per_mtok,
                                    settings.price_smart_output_per_mtok),
        settings.groq_model_fast: (settings.price_fast_input_per_mtok,
                                   settings.price_fast_output_per_mtok),
    }
    total = 0.0
    for model, usage in ledger.get("by_model", {}).items():
        in_rate, out_rate = rates.get(model, (0.0, 0.0))
        total += usage["input_tokens"] / 1_000_000 * in_rate
        total += usage["output_tokens"] / 1_000_000 * out_rate
    return round(total, 6)


def normalize_url(url: str) -> str:
    """Normalize URL by stripping tracking query params, trailing slashes, and lowercasing host."""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower() or "https"
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        # Filter out tracking query parameters (utm_*, ref, gclid, fbclid)
        ignored_params = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "fbclid", "gclid"}
        query_pairs = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in ignored_params]
        query = urlencode(query_pairs)

        return urlunparse((scheme, netloc, path, parsed.params, query, ""))
    except Exception:
        return url.strip().rstrip("/")


def sanitize_external_text(text: str) -> str:
    """Sanitize scraped web or RAG document text against prompt injection attempts."""
    if not text:
        return ""
    # Defuse common system override delimiters & instructions
    patterns = [
        r"(?i)\b(ignore\s+(all\s+)?(previous|prior)\s+instructions?)\b",
        r"(?i)\b(system\s*:\s*)",
        r"(?i)\b(you\s+are\s+now\s+(in\s+developer\s+mode|unrestricted))\b",
    ]
    cleaned = text
    for p in patterns:
        cleaned = re.sub(p, "[REDACTED_INSTRUCTION]", cleaned)
    return cleaned


def clean_llm_response(text: str) -> str:
    """Strip out reasoning/thinking tags like <think>...</think> if present."""
    if not text:
        return ""
    if "<think>" in text and "</think>" in text:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    elif "<think>" in text:
        text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    return text.strip()


# Error-text markers. The Groq/LangChain stack raises a mix of exception types
# whose only reliable shared signal is the message, so classification is done
# on the rendered text rather than on types that differ per transport.
_RETRYABLE = (
    "429", "rate_limit", "rate limit", "too many requests",
    "500", "502", "503", "504", "overloaded", "service unavailable",
    "timeout", "timed out", "connection", "temporarily unavailable",
    # If the server told us when to come back, the condition is transient by
    # definition — even when the status code isn't in the message text.
    "try again in",
)
_MODEL_UNAVAILABLE = (
    "model_not_found", "does not exist", "decommissioned",
    "model has been deprecated", "invalid model",
)

MAX_ATTEMPTS = 4
MAX_BACKOFF_SECONDS = 20.0


def _err_text(exc: Exception) -> str:
    return str(exc).lower()


def _is_retryable(exc: Exception) -> bool:
    """Retrying a malformed request or a bad key just burns time and quota —
    only transient conditions are worth a second attempt. The previous version
    retried on bare Exception, so a 400 was retried exactly as eagerly as a 429."""
    return any(m in _err_text(exc) for m in _RETRYABLE)


def _is_model_unavailable(exc: Exception) -> bool:
    return any(m in _err_text(exc) for m in _MODEL_UNAVAILABLE)


def _retry_after_seconds(exc: Exception) -> float | None:
    """Groq puts the wait in the error text ("Please try again in 7.5s") and
    sometimes in a retry-after header. Honouring it beats guessing: backing off
    for less than the server asked for just earns another 429."""
    text = str(exc)

    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers:
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if raw:
            try:
                return min(float(raw), MAX_BACKOFF_SECONDS)
            except (TypeError, ValueError):
                pass

    match = re.search(r"try again in\s+([0-9]*\.?[0-9]+)\s*(ms|s\b|seconds?)", text, re.I)
    if match:
        value = float(match.group(1))
        if match.group(2).lower() == "ms":
            value /= 1000.0
        return min(value, MAX_BACKOFF_SECONDS)
    return None


def _fallback_model_for(llm) -> str | None:
    """The alternate model to try when the requested one is unavailable.

    Deliberately limited to the two models configured for this deployment.
    The previous hardcoded list ("qwen/qwen3.6-27b", "allam-2-7b", ...) was
    guesswork — models that may not exist on the account at all, tried in
    silence, so a run could be answered by something entirely different from
    what was asked for with nothing in the logs to say so.
    """
    current = getattr(llm, "model_name", None) or getattr(llm, "model", None)
    settings = get_settings()
    for candidate in (settings.groq_model_smart, settings.groq_model_fast):
        if candidate and candidate != current:
            return candidate
    return None


def invoke_with_retry(llm, messages):
    """Invoke an LLM (or a structured-output runnable) with bounded retries.

    Transient failures get exponential backoff, honouring any server-supplied
    retry-after. If the model itself is unavailable, one substitution is tried
    and logged at WARNING — a silent swap changes answer quality invisibly,
    which is worse than the failure it papers over.

    Structured-output runnables are retried but never model-swapped: rebuilding
    one as a bare ChatGroq drops the schema, so the caller's isinstance() check
    fails and it quietly falls through to defaults. Every caller already has a
    JSON-prompt fallback for exactly this case; raising lets them use it.
    """
    last_exc: Exception | None = None
    is_plain_llm = isinstance(llm, BaseChatModel)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = llm.invoke(messages)
            _record_usage(response, getattr(llm, "model_name", None) or getattr(llm, "model", None))
            return response
        except Exception as exc:
            last_exc = exc

            if _is_model_unavailable(exc) and is_plain_llm:
                replacement = _fallback_model_for(llm)
                if replacement:
                    logger.warning(
                        "[LLM] Model %r unavailable (%s) — substituting %r. Output quality "
                        "for this call is not comparable to the requested model.",
                        getattr(llm, "model_name", "?"), str(exc)[:120], replacement,
                    )
                    from langchain_groq import ChatGroq
                    llm = ChatGroq(
                        model=replacement,
                        api_key=getattr(llm, "groq_api_key", None),
                        temperature=getattr(llm, "temperature", 0.3),
                        max_tokens=getattr(llm, "max_tokens", None),
                    )
                    continue
                raise

            if not _is_retryable(exc) or attempt == MAX_ATTEMPTS:
                raise

            wait = _retry_after_seconds(exc)
            if wait is None:
                wait = min(0.5 * (2 ** (attempt - 1)), MAX_BACKOFF_SECONDS)
            logger.info(
                "[LLM] Attempt %d/%d failed (%s) — retrying in %.1fs",
                attempt, MAX_ATTEMPTS, str(exc)[:100], wait,
            )
            time.sleep(wait)

    raise last_exc  # pragma: no cover — loop always returns or raises
