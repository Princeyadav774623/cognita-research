from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import re
from tenacity import Retrying, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging

logger = logging.getLogger(__name__)


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


def invoke_with_retry(llm, messages):
    """Call llm.invoke() with retry and automatic fallback across available Groq models if rate-limited."""
    try:
        retryer = Retrying(
            stop=stop_after_attempt(2),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )
        for attempt in retryer:
            with attempt:
                return llm.invoke(messages)
    except Exception as exc:
        err_msg = str(exc)
        if "429" in err_msg or "rate_limit" in err_msg or "model_not_found" in err_msg or "404" in err_msg:
            fallback_models = ["openai/gpt-oss-120b", "qwen/qwen3.6-27b", "openai/gpt-oss-20b", "allam-2-7b"]
            from langchain_groq import ChatGroq
            for fb_model in fallback_models:
                try:
                    if hasattr(llm, "model_name") and llm.model_name == fb_model:
                        continue
                    fb_llm = ChatGroq(
                        model=fb_model,
                        api_key=getattr(llm, "groq_api_key", None),
                        temperature=getattr(llm, "temperature", 0.3),
                        max_tokens=getattr(llm, "max_tokens", 1024),
                    )
                    return fb_llm.invoke(messages)
                except Exception:
                    continue
        raise exc

