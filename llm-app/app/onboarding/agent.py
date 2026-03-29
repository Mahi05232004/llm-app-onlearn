"""Standalone Onboarding Agent.

A lightweight agent for one-time user onboarding, separate from the
orchestrator graph. Uses the flash model for speed/cost efficiency.

The prompt is loaded from the module registry so each module (DSA, DS, etc.)
gets a tailored onboarding conversation.

Usage:
    from app.onboarding.agent import get_onboarding_agent

    agent = get_onboarding_agent(module_id="dsa")
    result = await agent.ainvoke(inputs, config=config)
"""

import logging
from typing import Any

from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict, Annotated

from app.tutor.core.config import get_tutor_model as get_onboarding_model
from core.checkpointer import get_checkpointer as get_tutor_checkpointer

logger = logging.getLogger(__name__)


# ── State ────────────────────────────────────────────────────────────

class OnboardingState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str


# ── Graph builder ────────────────────────────────────────────────────

def _build_onboarding_graph(system_prompt: str) -> StateGraph:
    """Build the onboarding agent graph with the given system prompt."""
    from app.tutor.core.tools.complete_onboarding import complete_onboarding

    from app.tutor.core.config import _get_client
    from config.settings import llm_config

    tools = [complete_onboarding]
    tool_node = ToolNode(tools)
    
    # 1. Primary Model: explicitly use "flash" (as per docstring) and fail fast
    client = _get_client()
    primary_model = client.get_model(model_type="flash", max_retries=1).bind_tools(tools)

    # 2. Fallback Model — skip if empty (no fallback configured, e.g. Azure single-deployment)
    fallback_name = llm_config.fallback_model or ""
    if fallback_name and fallback_name != client._resolve_model_name("flash"):
        fallback_model = client.get_model(model_type=fallback_name, max_retries=2).bind_tools(tools)
        model = primary_model.with_fallbacks([fallback_model])
    else:
        model = primary_model

    def chatbot(state: OnboardingState) -> dict:
        messages = state["messages"]
        response = model.invoke([
            ("system", system_prompt),
            *messages,
        ])
        return {"messages": [response]}

    def should_continue(state: OnboardingState) -> str:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(OnboardingState)
    graph.add_node("chatbot", chatbot)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("chatbot")
    graph.add_conditional_edges("chatbot", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "chatbot")
    return graph


# ── Singleton cache (one compiled agent per module) ──────────────────

_onboarding_agents: dict[str, Any] = {}


def get_onboarding_agent(module_id: str = "dsa"):
    """Get or create the compiled onboarding agent for the given module.

    Args:
        module_id: The learning module (e.g. 'dsa', 'ds').

    Returns:
        A compiled LangGraph agent with module-specific onboarding prompt.
    """
    global _onboarding_agents

    if module_id not in _onboarding_agents:
        from app.modules.registry import get_module
        config = get_module(module_id)
        prompt = config.onboarding_prompt
        logger.info("Creating onboarding agent for module: %s", module_id)

        graph = _build_onboarding_graph(prompt)
        _onboarding_agents[module_id] = graph.compile(
            checkpointer=get_tutor_checkpointer(),
        )

    return _onboarding_agents[module_id]

