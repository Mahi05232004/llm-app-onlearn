"""Tutor Agent — Exposure module."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph



_tutor_agents: dict[str, "CompiledStateGraph"] = {
    "dsa": None,
    "ds": None,
}

_fallback_agents: dict[str, "CompiledStateGraph"] = {
    "dsa": None,
    "ds": None,
}

def get_tutor_agent(module: str = "dsa") -> "CompiledStateGraph":
    """Get or create the singleton Tutor agent instance for the specific module.
    
    Args:
        module: The active learning module (e.g., "dsa" or "ds"). Defaults to "dsa".
    """
    global _tutor_agents
    
    # Fallback to dsa if module is unrecognizable
    if module not in _tutor_agents:
        module = "dsa"
        
    if _tutor_agents[module] is None:
        from app.tutor.core.store import get_tutor_store
        from app.tutor.core.config import get_tutor_model
        from core.checkpointer import get_checkpointer

        store = get_tutor_store()
        model = get_tutor_model(model_type="flash")
        checkpointer = get_checkpointer()
        
        if module == "dsa":
            from app.tutor.dsa.agent import create_dsa_agent
            _tutor_agents[module] = create_dsa_agent(
                model=model,
                store=store,
                checkpointer=checkpointer,
            )
        elif module == "ds":
            from app.tutor.ds.agent import create_ds_agent
            _tutor_agents[module] = create_ds_agent(
                model=model,
                store=store,
                checkpointer=checkpointer,
            )
            
    return _tutor_agents[module]


def get_fallback_tutor_agent(module: str = "dsa") -> "CompiledStateGraph":
    """Get or create a fallback Tutor agent.
    
    This agent is used when the primary model hits 429 rate limits.
    It shares the same store and checkpointer as the primary agent.
    """
    global _fallback_agents
    
    if module not in _fallback_agents:
        module = "dsa"
    
    if _fallback_agents[module] is None:
        import logging
        logger = logging.getLogger(__name__)
        
        from app.tutor.core.store import get_tutor_store
        from app.clients.llm_client import AzureLLMClient
        from config.settings import LLMConfig
        from core.checkpointer import get_checkpointer
        
        llm_config = LLMConfig()
        fallback_model_name = llm_config.fallback_model or "default"
        logger.info(f"Creating fallback agent with model: {fallback_model_name}")
        
        store = get_tutor_store()
        client = AzureLLMClient()
        model = client.get_model(model_type=fallback_model_name, max_retries=2)
        checkpointer = get_checkpointer()
        
        if module == "dsa":
            from app.tutor.dsa.agent import create_dsa_agent
            _fallback_agents[module] = create_dsa_agent(
                model=model,
                store=store,
                checkpointer=checkpointer,
            )
        elif module == "ds":
            from app.tutor.ds.agent import create_ds_agent
            _fallback_agents[module] = create_ds_agent(
                model=model,
                store=store,
                checkpointer=checkpointer,
            )
    
    return _fallback_agents[module]


__all__ = ["get_tutor_agent", "get_fallback_tutor_agent"]