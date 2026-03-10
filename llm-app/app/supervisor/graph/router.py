"""Router logic for the orchestrator graph."""

import json
import logging

from .state import OrchestratorState
from app.supervisor.tools.handoff import _read_routing_from_state

logger = logging.getLogger(__name__)

# Maximum number of agent invocations per user message turn
MAX_ITERATIONS = 4


def router(state: OrchestratorState) -> str:
    """Route to the appropriate agent based on state.
    
    Routing logic:
    1. If mode mismatch detected → master
    2. If active_agent is set → that agent
    3. Default → master
    
    Args:
        state: Current orchestrator state
        
    Returns:
        Agent name: 'master', 'concept_tutor', or 'lab_mentor'
    """
    routing = _read_routing_from_state(state)
    active_agent = routing.get("active_agent")
    
    current_mode = state.get("mode", "learn")
    expected_mode = routing.get("expected_mode")
    
    # Mode mismatch - return to master
    if active_agent and expected_mode and current_mode != expected_mode:
        return "master"
    
    # Route to active agent
    if active_agent == "concept_tutor":
        return "concept_tutor"
    elif active_agent == "lab_mentor":
        return "lab_mentor"
    else:
        return "master"


def post_agent_router(state: OrchestratorState) -> str:
    """Decide whether to loop back to the router or end the turn.
    
    Called after every agent node. Checks:
    1. Max iterations reached → END
    2. A delegation or handback happened (pending_handoff flag):
       a. If the agent ALSO produced visible text → END (one response per turn)
       b. If no visible text (silent delegation) → loop back to router
    3. Otherwise → END (agent responded normally)
    
    Args:
        state: Current orchestrator state
        
    Returns:
        'router' to loop back, or '__end__' to finish the turn
    """
    iteration = state.get("iteration", 0)
    
    # Safety cap
    if iteration >= MAX_ITERATIONS:
        logger.warning(f"Max iterations ({MAX_ITERATIONS}) reached, forcing END")
        return "__end__"
    
    # Check if a handoff happened during this agent's turn
    routing = _read_routing_from_state(state)
    if routing.get("pending_handoff"):
        # Check if the agent also produced visible text in this turn.
        # If yes → end the turn (student sees the greeting, next message
        #          goes to the new agent).
        # If no  → loop immediately (silent delegation).
        from langchain_core.messages import AIMessage
        messages = state.get("messages", [])
        has_visible_text = False
        for msg in reversed(messages[-10:]):
            if isinstance(msg, AIMessage) and msg.content:
                has_visible_text = True
                break
        
        if has_visible_text:
            logger.info(
                f"[Loop iter={iteration}] Handoff with visible text → ending turn. "
                f"Next agent: {routing.get('active_agent', 'master')}"
            )
            return "__end__"
        
        logger.info(
            f"[Loop iter={iteration}] Silent handoff → looping back to router. "
            f"Target: {routing.get('active_agent', 'master')}"
        )
        return "router"
    
    return "__end__"
