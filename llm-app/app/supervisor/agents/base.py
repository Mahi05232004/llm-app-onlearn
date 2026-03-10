"""Agent base factory using deepagents."""

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from deepagents import create_deep_agent


def create_agent(
    model: BaseChatModel,
    system_prompt: str,
    tools: list[BaseTool],
):
    """Create a deep agent with the given configuration.
    
    Args:
        model: LLM to use
        system_prompt: System prompt for the agent
        tools: List of tools available to the agent
        
    Returns:
        Compiled agent graph
    """
    return create_deep_agent(
        model=model,
        system_prompt=system_prompt,
        tools=tools,
    )
