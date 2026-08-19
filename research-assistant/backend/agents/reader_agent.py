import asyncio
import httpx
import requests
from bs4 import BeautifulSoup
import fitz  # PyMuPDF
from config import get_settings
from graph.state import ResearchState
from utils import normalize_url, sanitize_external_text
import logging

logger = logging.getLogger(__name__)
settings = get_settings()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 ResearchBot/2.0"
}
MAX_CHARS = 5000  # chars per source


# =============================================
# READER AGENT (Async + Incremental + Sanitized)
# =============================================

def reader_agent(state: ResearchState) -> ResearchState:
    """Synchronous entrypoint for LangGraph and unit tests."""
    existing_docs = list(state.get("source_documents", []))
    already_read_urls = {normalize_url(d["url"]) for d in existing_docs}

    results = state.get("search_results", [])
    unfetched = [r for r in results if normalize_url(r.get("url", "")) not in already_read_urls]

    logger.info(f"[ReaderAgent] Total candidate sources: {len(results)}, Already read: {len(already_read_urls)}, New to read: {len(unfetched)}")

    if not unfetched:
        return {
            **state,
            "source_documents": existing_docs,
            "current_step": "read_done",
        }

    documents = list(existing_docs)
    for result in unfetched:
        raw_url = result.get("url", "")
        url = normalize_url(raw_url)
        title = result.get("title", "Untitled")
        fallback_snippet = result.get("content", "")

        text = ""
        try:
            if url.endswith(".pdf"):
                text = extract_pdf(url)
            else:
                text = extract_webpage(url)
        except Exception as e:
            logger.warning(f"[ReaderAgent] Failed to read {url}: {e}")

        # Fallback to search result content if scraping failed or returned too little
        used_fallback = False
        if not text or len(text.strip()) < 100:
            if fallback_snippet and len(fallback_snippet.strip()) >= 40:
                text = fallback_snippet
                used_fallback = True

        text = sanitize_external_text(text)
        if text and len(text.strip()) >= 40:
            documents.append({
                "url": url,
                "title": title,
                "text": text[:MAX_CHARS],
                "via_fallback": used_fallback,
            })
            already_read_urls.add(url)
            tag = " (snippet fallback)" if used_fallback else ""
            logger.info(f"[ReaderAgent] ✓ Read ({len(text)} chars){tag}: {title[:50]}")
        else:
            logger.warning(f"[ReaderAgent] ✗ Empty content: {url}")

    logger.info(f"[ReaderAgent] Total accumulated documents: {len(documents)}")
    return {
        **state,
        "source_documents": documents,
        "current_step": "read_done",
    }


async def reader_agent_async(state: ResearchState) -> ResearchState:
    """High-throughput asynchronous parallel scraper for live graph execution."""
    existing_docs = list(state.get("source_documents", []))
    already_read_urls = {normalize_url(d["url"]) for d in existing_docs}

    results = state.get("search_results", [])
    unfetched = [r for r in results if normalize_url(r.get("url", "")) not in already_read_urls]

    logger.info(f"[ReaderAgent] Async reading: {len(unfetched)} new sources ({len(already_read_urls)} already cached)")
    if not unfetched:
        return {
            **state,
            "source_documents": existing_docs,
            "current_step": "read_done",
        }

    async with httpx.AsyncClient(headers=HEADERS, timeout=12.0, follow_redirects=True) as client:
        tasks = [fetch_single_source_async(client, r) for r in unfetched]
        fetched_docs = await asyncio.gather(*tasks, return_exceptions=True)

    new_documents = [doc for doc in fetched_docs if isinstance(doc, dict) and doc.get("text")]
    combined_docs = existing_docs + new_documents

    fallback_count = sum(1 for d in new_documents if d.get("via_fallback"))
    if fallback_count:
        logger.warning(
            f"[ReaderAgent] {fallback_count}/{len(new_documents)} new source(s) are search "
            "snippets, not full text — extraction was blocked or failed for these"
        )
    logger.info(f"[ReaderAgent] Successfully read {len(new_documents)} new documents (Total: {len(combined_docs)})")
    return {
        **state,
        "source_documents": combined_docs,
        "current_step": "read_done",
    }


async def fetch_single_source_async(client: httpx.AsyncClient, result: dict) -> dict | None:
    raw_url = result.get("url", "")
    url = normalize_url(raw_url)
    title = result.get("title", "Untitled")
    fallback_snippet = result.get("content", "")
    try:
        if url.endswith(".pdf"):
            resp = await client.get(url)
            resp.raise_for_status()
            text = await asyncio.to_thread(parse_pdf_bytes, resp.content)
        else:
            resp = await client.get(url)
            resp.raise_for_status()
            text = sanitize_html(resp.text)

        text = sanitize_external_text(text)
        if text and len(text.strip()) > 100:
            return {
                "url": url,
                "title": title,
                "text": text[:MAX_CHARS],
                "via_fallback": False,
            }
    except Exception as e:
        logger.warning(f"[ReaderAgent] Async fetch error for {url}: {e}")

    # Fallback to search result content if direct fetch failed
    if fallback_snippet and len(fallback_snippet.strip()) >= 40:
        return {
            "url": url,
            "title": title,
            "text": sanitize_external_text(fallback_snippet)[:MAX_CHARS],
            "via_fallback": True,
        }

    return None


def sanitize_html(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    # Strip non-content and potentially dangerous script/style tags
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe", "noscript"]):
        tag.decompose()

    main = soup.find("article") or soup.find("main") or soup.find("body")
    text = main.get_text(separator="\n", strip=True) if main else ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def extract_webpage(url: str) -> str:
    """Fetch a webpage synchronously and extract clean readable text."""
    response = requests.get(url, headers=HEADERS, timeout=10)
    response.raise_for_status()
    return sanitize_html(response.text)


def parse_pdf_bytes(content: bytes) -> str:
    doc = fitz.open(stream=content, filetype="pdf")
    pages_text = []
    for page_num in range(min(6, len(doc))):
        page = doc.load_page(page_num)
        pages_text.append(page.get_text())
    doc.close()
    return "\n".join(pages_text)


def extract_pdf(url: str) -> str:
    """Download and extract text from a PDF synchronously."""
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()
    return parse_pdf_bytes(response.content)

