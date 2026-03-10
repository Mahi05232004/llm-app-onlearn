"""
Standalone Data Science Onboarding Agent.

A lightweight agent for one-time DS user onboarding, separate from the main
orchestrator graph. Uses the flash model for speed/cost efficiency.

Mirrors onboarding.py but uses the DS-specific guide prompt so the
conversation focuses on Data Science / ML goals instead of DSA.

Usage:
    from app.supervisor.onboarding_ds import onboarding_ds_agent

    result = await onboarding_ds_agent.ainvoke(inputs, config=config)
"""

from deepagents import create_deep_agent

from app.supervisor.config import get_onboarding_model, get_checkpointer
from app.supervisor.prompts import GUIDE_DS_AGENT_PROMPT
from app.supervisor.tools.handoff import complete_onboarding


def create_onboarding_ds_agent():
    """Create the standalone DS onboarding agent.
    
    Uses create_deep_agent directly (not the base.create_agent wrapper) 
    so we can pass in the checkpointer for state persistence across
    multiple onboarding messages.
    
    The DS onboarding agent only gathers DS-specific information and calls
    complete_onboarding. Plan generation is handled separately
    by the planning service.
    
    Returns:
        Compiled deep agent configured for DS onboarding with:
        - Flash model (lightweight, fast)
        - complete_onboarding tool (profile submission only)
        - Checkpointer for state persistence
        - DS-specific guide prompt
    """
    model = get_onboarding_model()
    checkpointer = get_checkpointer()
    
    tools = [
        complete_onboarding,
    ]
    
    return create_deep_agent(
        model=model,
        system_prompt=GUIDE_DS_AGENT_PROMPT,
        tools=tools,
        checkpointer=checkpointer,
    )


# Singleton instance
onboarding_ds_agent = create_onboarding_ds_agent()
