"""Graph state definition for the orchestrator."""

from typing import Any, TypedDict, Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


def merge_files(existing: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Merge new files into existing files dict.
    
    This is critical for routing persistence: each new request sends
    frontend files (/plan.json, /topic.json), but we must NOT lose
    /routing.json that was written by delegate_to_agent on a previous turn.
    """
    if not existing:
        return new or {}
    if not new:
        return existing
    merged = {**existing, **new}
    return merged


class OrchestratorState(TypedDict):
    """State schema for the handoff orchestrator.
    
    Attributes:
        messages: Conversation message history (auto-accumulated)
        files: Virtual filesystem (merge-accumulated across turns)
        mode: Current mode - 'learn' or 'code'
        mode_changed: Flag indicating mode was changed mid-session
        user_id: MongoDB user ID for the authenticated user
        iteration: Loop iteration counter (for same-turn re-delegation safety cap)
    """
    messages: Annotated[list[BaseMessage], add_messages]
    files: Annotated[dict[str, Any], merge_files]
    mode: str
    mode_changed: bool
    user_id: str
    session_id: str
    iteration: int

