import logging
from typing import Annotated

from livekit.agents import llm

from src.knowledge.vectordb import KnowledgeBase

logger = logging.getLogger(__name__)


class AgentTools(llm.FunctionContext):
    """LLM function tools available to the voice agent."""

    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        super().__init__()
        self._kb = knowledge_base

    @llm.ai_callable(
        description=(
            "Look up information from the company knowledge base. Use this for any questions "
            "about policies (refunds, shipping, returns), product details, pricing, or "
            "company information. Always use this tool before answering policy questions."
        )
    )
    async def lookup_knowledge(
        self,
        query: Annotated[str, llm.TypeInfo(description="The customer's question or topic to search for")],
    ) -> str:
        """Query the knowledge base and return relevant context."""
        logger.info(f"Knowledge lookup: {query}")
        results = self._kb.query(query, n_results=3)

        if not results:
            return "No relevant information found in the knowledge base."

        context_parts = []
        for i, doc in enumerate(results, 1):
            context_parts.append(f"[{i}] {doc}")

        return "Relevant information from our knowledge base:\n" + "\n\n".join(context_parts)
