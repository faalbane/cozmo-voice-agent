"""Tests for the knowledge base module."""

import pytest
from unittest.mock import patch, MagicMock

from src.knowledge.ingest import chunk_document


class TestChunkDocument:
    def test_single_paragraph(self):
        text = "This is a short paragraph."
        chunks = chunk_document(text, chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0] == "This is a short paragraph."

    def test_multiple_paragraphs_within_limit(self):
        text = "First paragraph.\n\nSecond paragraph."
        chunks = chunk_document(text, chunk_size=500)
        assert len(chunks) == 1

    def test_splits_on_chunk_size(self):
        text = "A" * 300 + "\n\n" + "B" * 300
        chunks = chunk_document(text, chunk_size=400, overlap=5)
        assert len(chunks) >= 2

    def test_empty_text(self):
        chunks = chunk_document("")
        assert chunks == []

    def test_preserves_content(self):
        text = "Important policy info.\n\nRefund details here.\n\nShipping info."
        chunks = chunk_document(text, chunk_size=1000)
        combined = " ".join(chunks)
        assert "Important policy info" in combined
        assert "Refund details" in combined
        assert "Shipping info" in combined
