"""Knowledge base tool for the Pipecat voice agent.

Registers a function the LLM can call to query the ChromaDB knowledge base
during conversation.
"""

import json
import logging

from src.knowledge.vectordb import KnowledgeBase

logger = logging.getLogger(__name__)

_kb = None


def _get_kb() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb


KNOWLEDGE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "lookup_knowledge",
        "description": (
            "Search the company knowledge base for information about policies, "
            "products, shipping, refunds, or any customer question. Always use "
            "this before answering policy-related questions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The customer question or topic to search for",
                }
            },
            "required": ["query"],
        },
    },
}


async def handle_knowledge_lookup(function_name, tool_call_id, args, llm, context, result_callback):
    """Handle a knowledge base lookup function call from the LLM."""
    query = args.get("query", "")
    logger.info(f"Knowledge lookup: {query}")

    try:
        kb = _get_kb()
        results = kb.query(query, n_results=3)

        if results:
            context_text = "\n\n".join(f"[{i+1}] {doc}" for i, doc in enumerate(results))
            response = f"Relevant information from our knowledge base:\n{context_text}"
        else:
            response = "No relevant information found in the knowledge base."

    except Exception as e:
        logger.error(f"Knowledge base query failed: {e}")
        response = "I wasn't able to search our knowledge base right now. Let me answer based on what I know."

    await result_callback(response)


def register_knowledge_tools(llm, context):
    """Register the knowledge base tool with the LLM service."""
    # Add tool definition to the context
    context.set_tools([KNOWLEDGE_TOOL_SCHEMA])

    # Register the handler
    llm.register_function("lookup_knowledge", handle_knowledge_lookup)

    logger.info("Knowledge base tool registered with LLM")
