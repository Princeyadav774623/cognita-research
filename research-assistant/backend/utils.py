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


def invoke_with_retry(llm, messages):
    """Call llm.invoke() with up to 3 attempts and exponential backoff."""
    retryer = Retrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    for attempt in retryer:
        with attempt:
            return llm.invoke(messages)

