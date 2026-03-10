"""Tool functions for the supervisor orchestrator.

Available tools:
- course: Curriculum navigation (get_steps, get_sub_steps, get_questions)
- handoff: Agent routing (delegate_to_agent, hand_back_to_master, complete_onboarding)
- execute: Code execution via Judge0
"""

from .course import get_steps, get_sub_steps, get_questions
from .handoff import delegate_to_agent, hand_back_to_master, complete_onboarding
from .execute import execute_code_tool
from .memory import (
    list_recent_sessions,
    get_session_detail,
    get_cross_mode_context,
    update_session_note,
    get_current_session_note,
    memory_tools
)

__all__ = [
    # Course tools
    "get_steps",
    "get_sub_steps", 
    "get_questions",
    # Handoff tools
    "delegate_to_agent",
    "hand_back_to_master",
    "complete_onboarding",
    # Execute tools
    "execute_code_tool",
    # Memory tools
    "list_recent_sessions",
    "get_session_detail",
    "get_cross_mode_context",
    "update_session_note",
    "get_current_session_note",
    "memory_tools",
]
