"""
Memory tools for the Master Agent and sub-agents.

These tools allow agents to access memory across sessions and modes:
- `list_recent_sessions`: See what the student worked on recently (with notes)
- `get_session_detail`: Read full messages from a specific past session
- `get_cross_mode_context`: See messages from the OTHER mode in the CURRENT session
- `update_session_note`: Write a summary note for the current session
- `get_current_session_note`: Read the manual note for the current session
"""

from typing import Annotated, List, Dict, Any, Optional
import json
import logging
from datetime import datetime, UTC
from bson import ObjectId

from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.prebuilt import InjectedState

from app.supervisor.graph.state import OrchestratorState
from core.mongo_db import mongo_db_manager

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────

def _get_db():
    """Get the MongoDB database instance."""
    return mongo_db_manager.get_database()

def _format_session_summary(session: Dict[str, Any]) -> str:
    """Format a session document into a concise summary string."""
    topic = session.get("topicId", "Unknown Topic")
    title = session.get("title", "Untitled Session")
    note = session.get("note")
    updated_at = session.get("updatedAt", datetime.now(UTC))
    
    # Simple status inference based on last message
    status = "in_progress"
    messages = session.get("messages", [])
    if messages:
        last_msg = messages[-1]
        content = last_msg.get("content", "")
        if isinstance(content, str) and "objective_complete" in content:
            status = "completed"
    
    summary = f"- [{updated_at.strftime('%Y-%m-%d')}] **{title}** ({topic})\n  Status: {status}\n  Session ID: {str(session['_id'])}"
    if note:
        summary += f"\n  Note: {note}"
    
    return summary

def _format_message(msg: Dict[str, Any]) -> str:
    """Format a message dictionary into a readable string."""
    role = msg.get("role", "unknown")
    content = msg.get("content", "")
    if isinstance(content, list):
        # Handle structured content blocks: [{type: 'reasoning', reasoning: '...'}, {type: 'text', text: '...'}]
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text" and "text" in block:
                    parts.append(block["text"])
                elif block.get("type") == "reasoning" and "reasoning" in block:
                    parts.append(f"[Thinking: {block['reasoning'][:100]}...]")
        content = "\n".join(parts) if parts else str(content)
    
    return f"**{role.upper()}**: {content}"


# ──────────────────────────────────────────────
# Memory Tools
# ──────────────────────────────────────────────

@tool
def list_recent_sessions(
    limit: Annotated[int, "Number of recent sessions to retrieve (default 5, max 20)"] = 5,
    state: Annotated[OrchestratorState, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """
    Get a list of the student's recent learning sessions.
    
    Use this to:
    - See what topics the student was working on recently
    - Check the status of past sessions (completed vs in-progress)
    - Read summary notes left by previous agents
    
    Returns a formatted list of sessions with topic, title, date, status, and notes.
    """
    if not state:
        return Command(
            update={"messages": [ToolMessage(content="Error: state not injected. Cannot access user data.", tool_call_id=tool_call_id)]}
        )
    user_id = state.get("user_id")
    if not user_id:
        return Command(
            update={
                "messages": [ToolMessage(content="Error: No user_id in state.", tool_call_id=tool_call_id)]
            }
        )
    
    limit = min(max(1, limit), 20)
    db = _get_db()
    
    try:
        # Query recent sessions for this user
        cursor = db.chatsessions.find(
            {"userId": ObjectId(user_id)},
            {
                "topicId": 1, 
                "title": 1, 
                "note": 1, 
                "updatedAt": 1, 
                "messages": {"$slice": -1}  # Get last message to infer status
            }
        ).sort("updatedAt", -1).limit(limit)
        
        sessions = list(cursor)
        
        if not sessions:
            return Command(
                update={
                    "messages": [ToolMessage(content="No recent sessions found.", tool_call_id=tool_call_id)]
                }
            )
        
        summary_lines = ["Here are the student's recent sessions (substitute for your memory):"]
        for session in sessions:
            summary_lines.append(_format_session_summary(session))
            
        return Command(
            update={
                "messages": [ToolMessage(content="\n\n".join(summary_lines), tool_call_id=tool_call_id)]
            }
        )
        
    except Exception as e:
        logger.error(f"Error listing recent sessions: {e}", exc_info=True)
        return Command(
            update={
                "messages": [ToolMessage(content=f"Error accessing database: {str(e)}", tool_call_id=tool_call_id)]
            }
        )


@tool
def get_session_detail(
    session_id: Annotated[str, "The ID of the session to retrieve"],
    mode: Annotated[Optional[str], "Filter messages by mode ('learn' or 'code'). If omitted, returns all messages."] = None,
    offset: Annotated[int, "Start reading from this message index (0-based). Use this to page through long sessions. Default: show last `limit` messages."] = -1,
    limit: Annotated[int, "Max number of messages to return (default 30, max 50)"] = 30,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """
    Read messages from a specific past session with pagination.
    
    Use this when:
    - The student references a specific past conversation
    - You want to see exactly what code they wrote in a previous session
    - You want to see exactly how a concept was explained previously
    
    By default returns the LAST 30 messages. To browse earlier parts, use `offset`:
    - offset=0, limit=30  → first 30 messages
    - offset=30, limit=30 → messages 30-59
    - offset=-1 (default) → last `limit` messages
    """
    if not session_id:
        return Command(
            update={
                "messages": [ToolMessage(content="Error: Session ID is required.", tool_call_id=tool_call_id)]
            }
        )
    
    limit = min(max(1, limit), 50)
    db = _get_db()
    
    try:
        session = db.chatsessions.find_one({"_id": ObjectId(session_id)})
        
        if not session:
            return Command(
                update={
                    "messages": [ToolMessage(content=f"Session {session_id} not found.", tool_call_id=tool_call_id)]
                }
            )
            
        messages = session.get("messages", [])
        
        # Filter by mode if requested
        if mode:
            messages = [m for m in messages if m.get("mode") == mode]
        
        total = len(messages)
        
        # Apply pagination
        if offset < 0:
            # Default: show last N messages
            start = max(0, total - limit)
            end = total
        else:
            start = min(offset, total)
            end = min(start + limit, total)
        
        page = messages[start:end]
        
        formatted_msgs = []
        for i, msg in enumerate(page):
            formatted_msgs.append(f"[{start + i}] {_format_message(msg)}")
        
        # Header with pagination info
        header = f"### Session Detail: {session.get('title')} ({session_id})\n"
        header += f"Mode: {mode or 'All'} | Showing messages {start}-{end - 1} of {total}\n"
        if start > 0:
            header += f"_Use offset=0 to see earlier messages._\n"
        if end < total:
            header += f"_Use offset={end} to see next page._\n"
        
        content = header + "\n" + "\n\n".join(formatted_msgs)
        
        return Command(
            update={
                "messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]
            }
        )
        
    except Exception as e:
        logger.error(f"Error getting session detail: {e}", exc_info=True)
        return Command(
            update={
                "messages": [ToolMessage(content=f"Error accessing database: {str(e)}", tool_call_id=tool_call_id)]
            }
        )


@tool
def get_cross_mode_context(
    state: Annotated[OrchestratorState, InjectedState] = None,
    limit: Annotated[int, "Number of messages to retrieve (default 10)"] = 10,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """
    Get messages from the OTHER mode in the CURRENT session.
    
    Use this when:
    - You are in 'learn' mode and want to see what code the student wrote in 'code' mode
    - You are in 'code' mode and want to see what concepts were explained in 'learn' mode
    
    Returns the data from the opposite thread.
    """
    if not state:
        return Command(
            update={"messages": [ToolMessage(content="Error: state not injected. Cannot access session data.", tool_call_id=tool_call_id)]}
        )
    session_id = state.get("session_id")
    current_mode = state.get("mode", "learn")
    target_mode = "code" if current_mode == "learn" else "learn"
    
    if not session_id:
        return Command(
            update={
                "messages": [ToolMessage(content="Error: No session_id in state.", tool_call_id=tool_call_id)]
            }
        )
        
    db = _get_db()
    
    try:
        # We need to fetch the session to get the full message history
        # because the current state only contains the ACTIVE thread's messages
        session = db.chatsessions.find_one({"_id": ObjectId(session_id)})
        
        if not session:
            return Command(
                update={
                    "messages": [ToolMessage(content=f"Current session {session_id} not found in DB.", tool_call_id=tool_call_id)]
                }
            )
            
        messages = session.get("messages", [])
        
        # Filter for the target mode
        target_messages = [m for m in messages if m.get("mode") == target_mode]
        
        # Take the most recent ones
        recent_target_messages = target_messages[-limit:] if limit > 0 else target_messages
        
        if not recent_target_messages:
            return Command(
                update={
                    "messages": [ToolMessage(content=f"No messages found in {target_mode} mode for this session.", tool_call_id=tool_call_id)]
                }
            )
            
        formatted_msgs = []
        for msg in recent_target_messages:
            formatted_msgs.append(_format_message(msg))
            
        content = f"### Cross-Mode Context ({target_mode.upper()} mode)\n\n" + "\n\n".join(formatted_msgs)
        
        return Command(
            update={
                "messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]
            }
        )
        
    except Exception as e:
        logger.error(f"Error getting cross-mode context: {e}", exc_info=True)
        return Command(
            update={
                "messages": [ToolMessage(content=f"Error accessing database: {str(e)}", tool_call_id=tool_call_id)]
            }
        )


@tool
def update_session_note(
    note: Annotated[str, "The summary note to save for this session"],
    state: Annotated[OrchestratorState, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """
    Write or update the summary note for the CURRENT session.
    
    Call this when:
    - The student reaches a milestone (e.g. "Understood binary search concept")
    - The student hits a roadblock (e.g. "Struggling with off-by-one errors")
    - The session is ending or switching topics
    
    This note will be visible to you and other agents in future sessions via `list_recent_sessions`.
    Keep it concise and pedagogically relevant.
    """
    if not state:
        return Command(
            update={"messages": [ToolMessage(content="Error: state not injected.", tool_call_id=tool_call_id)]}
        )
    session_id = state.get("session_id")
    
    if not session_id:
        return Command(
            update={
                "messages": [ToolMessage(content="Error: No session_id in state.", tool_call_id=tool_call_id)]
            }
        )
        
    db = _get_db()
    
    try:
        result = db.chatsessions.update_one(
            {"_id": ObjectId(session_id)},
            {"$set": {"note": note}}
        )
        
        if result.modified_count == 0 and result.matched_count == 0:
             return Command(
                update={
                    "messages": [ToolMessage(content="Error: Session not found.", tool_call_id=tool_call_id)]
                }
            )
            
        return Command(
            update={
                "messages": [ToolMessage(content="Session note updated successfully.", tool_call_id=tool_call_id)]
            }
        )
        
    except Exception as e:
        logger.error(f"Error updating session note: {e}", exc_info=True)
        return Command(
            update={
                "messages": [ToolMessage(content=f"Error accessing database: {str(e)}", tool_call_id=tool_call_id)]
            }
        )


@tool
def get_current_session_note(
    state: Annotated[OrchestratorState, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """
    Read the summary note for the CURRENT session.
    
    Use this to see what high-level progress has been recorded so far in this session,
    especially if you are a sub-agent taking over mid-session.
    """
    if not state:
        return Command(
            update={"messages": [ToolMessage(content="Error: state not injected.", tool_call_id=tool_call_id)]}
        )
    session_id = state.get("session_id")
    
    if not session_id:
        return Command(
            update={
                "messages": [ToolMessage(content="Error: No session_id in state.", tool_call_id=tool_call_id)]
            }
        )
        
    db = _get_db()
    
    try:
        session = db.chatsessions.find_one(
            {"_id": ObjectId(session_id)},
            {"note": 1}
        )
        
        if not session:
            return Command(
                update={
                    "messages": [ToolMessage(content="Error: Session not found.", tool_call_id=tool_call_id)]
                }
            )
            
        note = session.get("note", "No note recorded for this session yet.")
        
        return Command(
            update={
                "messages": [ToolMessage(content=f"Current Session Note:\n{note}", tool_call_id=tool_call_id)]
            }
        )
        
    except Exception as e:
        logger.error(f"Error getting current session note: {e}", exc_info=True)
        return Command(
            update={
                "messages": [ToolMessage(content=f"Error accessing database: {str(e)}", tool_call_id=tool_call_id)]
            }
        )


# Export tool list (update_session_note is NOT included — it's handled
# automatically by the master node wrapper after handbacks)
memory_tools = [
    list_recent_sessions,
    get_session_detail,
    get_cross_mode_context,
    get_current_session_note
]
