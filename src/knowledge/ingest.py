"""Ingest knowledge documents into ChromaDB."""

import logging
import os
from pathlib import Path

from src.knowledge.vectordb import KnowledgeBase

logger = logging.getLogger(__name__)

DOCUMENTS_DIR = Path(__file__).parent / "documents"


def chunk_document(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split document into overlapping chunks for embedding."""
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) > chunk_size and current_chunk:
            chunks.append(current_chunk.strip())
            # Keep overlap from end of previous chunk
            words = current_chunk.split()
            overlap_words = words[-overlap:] if len(words) > overlap else words
            current_chunk = " ".join(overlap_words) + "\n\n" + para
        else:
            current_chunk += ("\n\n" if current_chunk else "") + para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def ingest_all() -> int:
    """Ingest all markdown documents from the documents directory."""
    kb = KnowledgeBase()
    total_chunks = 0

    for md_file in sorted(DOCUMENTS_DIR.glob("*.md")):
        text = md_file.read_text()
        source = md_file.stem

        chunks = chunk_document(text)
        ids = [f"{source}-{i}" for i in range(len(chunks))]
        metadatas = [{"source": source, "chunk_index": i} for i in range(len(chunks))]

        kb.add_documents(documents=chunks, metadatas=metadatas, ids=ids)
        total_chunks += len(chunks)
        logger.info(f"Ingested {len(chunks)} chunks from {md_file.name}")

    logger.info(f"Total: {total_chunks} chunks ingested into knowledge base")
    return total_chunks


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ingest_all()
