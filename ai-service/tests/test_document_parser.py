from __future__ import annotations

import pytest

from app.rag.document_parser import extract_text_from_bytes


def test_extract_txt() -> None:
    text = extract_text_from_bytes("note.txt", b"Radar fault during track.")
    assert "Radar fault" in text


def test_extract_md() -> None:
    text = extract_text_from_bytes("report.md", b"# Incident\n\nGimbal drift observed.")
    assert "Gimbal drift" in text


def test_reject_unsupported() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        extract_text_from_bytes("image.png", b"not-a-document")


def test_reject_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        extract_text_from_bytes("empty.txt", b"")
