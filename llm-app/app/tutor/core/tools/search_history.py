from langchain_core.tools import tool, InjectedToolArg
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore
from typing import Annotated

@tool(parse_docstring=True)
async def search_history(query: str, store: Annotated[BaseStore, InjectedToolArg()], config: Annotated[RunnableConfig, InjectedToolArg()]) -> str:
    """Use this to recall exact details from past sessions — across ALL questions.
    
    Example: search_history('python loops homework code')
    
    Args:
        query: The semantic search string describing the context you need to remember.
    """
    user_id = config["configurable"].get("assistant_id")
    namespace = ("conversation_history", user_id)
    
    # Execute semantic search against the chunked MongoDB index (per-user, cross-session)
    results = await store.asearch(namespace=namespace, query=query, limit=3)
    
    if not results:
        return "No relevant historical conversations found."
        
    return "\n\n---\n\n".join([r.value["content"] for r in results])

