import logging
import uuid
from typing import Any
from langchain_core.messages import AnyMessage, get_buffer_string, HumanMessage
from langgraph.config import get_config
from deepagents.middleware.summarization import SummarizationMiddleware

logger = logging.getLogger(__name__)


class SemanticSummarizationMiddleware(SummarizationMiddleware):
    """
    Subclasses the base SummarizationMiddleware to offload chunks 
    into a semantic vector database instead of a linear Markdown file.
    
    Uses per-USER namespace (not per-thread) for cross-session recall.
    """

    def _get_user_id(self) -> str:
        """Extract user_id (assistant_id) from langgraph config.
        
        Mirrors _get_thread_id() pattern but reads assistant_id instead.
        """
        try:
            config = get_config()
            user_id = config.get("configurable", {}).get("assistant_id")
            if user_id is not None:
                return str(user_id)
        except RuntimeError:
            pass
        
        # Fallback: try thread_id
        logger.warning("No assistant_id in config, falling back to thread_id for vector namespace")
        return self._get_thread_id()
    
    async def _aoffload_to_backend(self, backend: Any, messages: list[AnyMessage]) -> str | None:
        """Overrides the single Markdown file tape with a chunked vector RAG namespace.
        
        Uses per-USER namespace (not per-thread) to enable cross-session recall.
        """
        user_id = self._get_user_id()
        filtered_messages = self._filter_summary_messages(messages)
        content_string = get_buffer_string(filtered_messages)
        
        # 1. Grab the actual LangGraph BaseStore from the backend tool runtime wrapper
        if hasattr(backend, "_tool_runtime"):
            store = backend._tool_runtime.store 
        else:
            store = backend
        
        # 2. We generate a unique chunk ID for this summarization event
        chunk_id = str(uuid.uuid4())
        
        # 3. Store the chunk under per-USER namespace for cross-session recall
        namespace = ("conversation_history", user_id)
        
        # 4. Asynchronously put the chunk into the MongoDB store index
        await store.aput(
            namespace=namespace,
            key=chunk_id,
            value={"type": "history_chunk", "content": content_string},
            index=True  # Enables semantic indexing
        )
        return chunk_id

    def _build_new_messages_with_path(self, summary: str, chunk_id: str | None) -> list[AnyMessage]:
        """Tells the LLM how to retrieve its semantic memory."""
        content = f"""You are in the middle of a continuous conversation spanning several months. A portion of this immediate chat was just algorithmically summarized to save you tokens.
        
<summary>
{summary}
</summary>

CRITICAL INSTRUCTION: Your deep, raw, long-term history is archived in a vector database. To retrieve exact context about past sessions, you must use the `search_history` tool with semantic keywords."""
        
        return [HumanMessage(content=content, additional_kwargs={"lc_source": "summarization"})]
