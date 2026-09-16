import io
import logging

from utils import sanitize_external_text

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "md", "png", "jpg", "jpeg"}
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB
MAX_PDF_PAGES = 200


class IngestError(Exception):
    """Raised when a file can't be parsed into text."""


def validate_file_signature(ext: str, content: bytes) -> None:
    """Sniff magic bytes to ensure file contents match declared extension."""
    if not content:
        raise IngestError("File content is empty")

    if ext == "pdf":
        if not content.startswith(b"%PDF-"):
            raise IngestError("Corrupted or invalid PDF header (magic bytes do not match %PDF-)")
    elif ext == "docx":
        if not content.startswith(b"PK\x03\x04"):
            raise IngestError("Invalid DOCX format (missing PK zip archive signature)")
    elif ext == "png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise IngestError("Invalid PNG image header")
    elif ext in ("jpg", "jpeg"):
        if not content.startswith(b"\xff\xd8\xff"):
            raise IngestError("Invalid JPEG image header")
    elif ext in ("txt", "md"):
        if b"\x00" in content[:1024]:
            raise IngestError("Text file contains invalid binary/null bytes")


def extract_text(filename: str, content: bytes) -> str:
    """Extract readable text from an uploaded file.

    Output is passed through the same injection sanitiser as scraped web pages.
    That was applied to everything the reader agent fetched but never to
    uploaded documents — so a file was the one path into the model's context
    that nothing filtered, despite being the easiest one for an attacker to
    control. Anyone who can upload can write whatever they like.

    The sanitiser is a speed bump, not a wall — the real defence is that
    retrieved text is delimited and labelled as data in the prompt (see
    rag/chat_agent._format_context). Both matter; neither is sufficient alone.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in ALLOWED_EXTENSIONS:
        raise IngestError(f"Unsupported file type: .{ext}")

    if len(content) > MAX_FILE_SIZE_BYTES:
        raise IngestError(f"File too large ({len(content) // 1_000_000}MB, max 15MB)")

    # Validate actual file bytes against extension signature
    validate_file_signature(ext, content)

    if ext == "pdf":
        text = _extract_pdf(content)
    elif ext == "docx":
        text = _extract_docx(content)
    elif ext in ("txt", "md"):
        text = _extract_text_file(content)
    elif ext in ("png", "jpg", "jpeg"):
        text = _extract_image_ocr(content)
    else:
        raise IngestError(f"Unsupported file type: .{ext}")

    return sanitize_external_text(text)


def _extract_pdf(content: bytes) -> str:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=content, filetype="pdf")
    try:
        pages = [doc.load_page(i).get_text() for i in range(min(MAX_PDF_PAGES, len(doc)))]
    finally:
        doc.close()
    text = "\n".join(pages).strip()
    if not text:
        raise IngestError("No extractable text found in PDF (it may be a scanned image PDF)")
    return text


def _extract_docx(content: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(content))
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if not text.strip():
        raise IngestError("No extractable text found in DOCX")
    return text


def _extract_text_file(content: bytes) -> str:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1", errors="ignore")
    if not text.strip():
        raise IngestError("File is empty")
    return text


def _extract_image_ocr(content: bytes) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        raise IngestError("Image OCR dependencies not installed") from e

    try:
        image = Image.open(io.BytesIO(content))
        text = pytesseract.image_to_string(image)
    except pytesseract.TesseractNotFoundError as e:
        raise IngestError(
            "OCR engine (tesseract) is not installed on this server. "
            "Install it with `brew install tesseract` (dev) or `apt-get install tesseract-ocr` (Docker)."
        ) from e

    if not text.strip():
        raise IngestError("No text could be read from this image")
    return text


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    """Split text into overlapping chunks so context isn't lost at chunk
    boundaries — important for retrieval quality on longer documents."""
    text = text.strip()
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = end - overlap
    return chunks
