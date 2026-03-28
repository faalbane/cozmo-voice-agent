"""ChromaDB-backed knowledge base for the voice agent."""

import logging
import os

import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "shopease_knowledge"


class KnowledgeBase:
    """Vector similarity search over company knowledge documents."""

    def __init__(self) -> None:
        chroma_host = os.getenv("CHROMA_HOST", "localhost")
        chroma_port = int(os.getenv("CHROMA_PORT", "8000"))

        try:
            self._client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
        except Exception:
            # Fall back to ephemeral client for local dev/testing
            logger.warning("ChromaDB server unavailable, using ephemeral client")
            self._client = chromadb.EphemeralClient()

        self._embedding_fn = OpenAIEmbeddingFunction(
            api_key=os.getenv("OPENAI_API_KEY"),
            model_name="text-embedding-3-small",
        )

        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    def add_documents(self, documents: list[str], metadatas: list[dict], ids: list[str]) -> None:
        """Add documents to the knowledge base."""
        self._collection.upsert(
            documents=documents,
            metadatas=metadatas,
            ids=ids,
        )
        logger.info(f"Added {len(documents)} documents to knowledge base")

    def query(self, query_text: str, n_results: int = 3) -> list[str]:
        """Query the knowledge base and return matching document texts."""
        try:
            results = self._collection.query(
                query_texts=[query_text],
                n_results=n_results,
            )
            return results["documents"][0] if results["documents"] else []
        except Exception as e:
            logger.error(f"Knowledge base query failed: {e}")
            return []

    def collection_count(self) -> int:
        """Return the number of documents in the collection."""
        return self._collection.count()
