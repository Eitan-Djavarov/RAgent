from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader


SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown"}


def extract_text_from_bytes(filename: str, content: bytes) -> str:
    """Extract plain text from PDF, TXT, or Markdown uploads."""
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{extension}'. Allowed: {sorted(SUPPORTED_EXTENSIONS)}"
        )
    if not content:
        raise ValueError("Uploaded file is empty.")

    if extension == ".pdf":
        return _extract_pdf(content)
    return content.decode("utf-8", errors="replace").strip()


def _extract_pdf(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        cleaned = text.strip()
        if cleaned:
            pages.append(cleaned)
    combined = "\n\n".join(pages).strip()
    if not combined:
        raise ValueError("No extractable text found in PDF.")
    return combined
