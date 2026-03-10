"""
Supervisor Orchestrator: Main entry point.

This module provides the compiled orchestrator graph that routes messages
between Master Agent, Concept Tutor, Lab Mentor, and Guide Agent.

Usage:
    from app.supervisor.orchestrator import orchestrator
    
    result = await orchestrator.ainvoke(inputs, config=config)
"""

from app.supervisor.config import get_model, get_checkpointer
from app.supervisor.graph import build_graph


def create_orchestrator():
    """Create the compiled orchestrator graph.
    
    Returns:
        Compiled StateGraph with all agents configured
    """
    model = get_model(model_type="pro")
    checkpointer = get_checkpointer()
    
    return build_graph(model=model, checkpointer=checkpointer)


# Export the compiled orchestrator as a singleton
orchestrator = create_orchestrator()

# Backwards compatibility alias
master_orchestrator = orchestrator
