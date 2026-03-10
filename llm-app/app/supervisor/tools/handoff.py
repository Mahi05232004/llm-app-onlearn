"""Handoff tools for sub-agents to communicate with the master orchestrator.

These tools allow:
1. Master Agent to delegate control to sub-agents
2. Sub-agents to hand control back to Master Agent
3. Guide Agent to complete onboarding

ARCHITECTURE NOTE:
- delegate_to_agent and hand_back_to_master return plain JSON strings
  (not Command objects) because the inner deep agent's state schema
  doesn't include 'files', so Command(update={"files": ...}) gets
  silently dropped.
- The node wrappers in nodes.py are responsible for extracting routing
  data from tool messages and persisting it in the outer graph's files.
"""

from typing import Annotated
import json

from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.types import Command


# Routing file path (relative to virtual FS root)
ROUTING_FILE = "/routing.json"

# Module-level side channel for routing data.
# When delegate_to_agent or hand_back_to_master runs, it stores
# the routing update here as a side effect. The node wrapper reads
# this after ainvoke() — even if the model crashes with ValueError
# (empty stream), this data survives because the tool ran first.
_pending_routing: dict = {}


def _read_routing_from_state(state: dict) -> dict:
    """Read current routing state from state's virtual filesystem.
    
    Handles content as either a string or list-of-lines (StateBackend format).
    """
    files = state.get("files", {})
    routing_data = files.get(ROUTING_FILE, {})
    if isinstance(routing_data, dict) and "content" in routing_data:
        content = routing_data["content"]
        # Handle list-of-lines format from StateBackend
        if isinstance(content, list):
            content = "\n".join(content)
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _write_routing(data: dict) -> dict:
    """Write routing state to virtual filesystem. Returns files_update for Command."""
    content = json.dumps(data, indent=2)
    return {
        ROUTING_FILE: {
            "content": content,
            "metadata": {"type": "routing"}
        }
    }


@tool
def delegate_to_agent(
    agent_name: Annotated[str, "Name of the sub-agent to delegate to: 'concept_tutor' or 'lab_mentor'"],
    objective: Annotated[str, "Clear objective for the sub-agent. Be specific about what needs to be accomplished."],
    expected_mode: Annotated[str, "The mode this agent expects: 'learn' or 'code'"],
    question_id: Annotated[str, "The question_id/topic_id the student is currently working on. Get this from /topic.json."],
) -> str:
    """
    Delegate control to a sub-agent. The sub-agent will handle ALL subsequent 
    user messages until it calls hand_back_to_master().
    
    Use this when:
    - You've decided on the next learning objective
    - The student needs focused tutoring on a concept (use concept_tutor)
    - The student needs help with coding practice (use lab_mentor)
    
    IMPORTANT: Always include the question_id from /topic.json.
    
    The sub-agent will receive:
    - The objective you provide
    - Full question context (concepts, approaches, problem) loaded from course data
    - All future user messages until handoff
    """
    routing_data = {
        "action": "delegate",
        "routing": {
            "active_agent": agent_name,
            "objective": objective,
            "expected_mode": expected_mode,
            "question_id": question_id,
        },
    }
    # Side-channel: store for node wrapper to read even if model crashes
    global _pending_routing
    _pending_routing = routing_data["routing"]
    return json.dumps(routing_data)


@tool  
def hand_back_to_master(
    summary: Annotated[str, "Summary of what was accomplished during this session"],
    reason: Annotated[str, "Reason for handing back: 'objective_complete', 'mode_mismatch', 'user_request', 'need_guidance'"],
) -> str:
    """
    Hand control back to the Master Agent.
    
    Call this when:
    - You've completed the assigned objective
    - The user's mode changed (they switched from Learn to Code or vice versa)
    - The user explicitly asks to talk to the "main" agent or change topics
    - You need the Master Agent to make a planning decision
    
    The Master Agent will:
    - Receive your summary
    - Decide the next steps
    - Potentially delegate to you or another agent
    """
    routing_data = {
        "action": "handback",
        "routing": {
            "active_agent": None,
            "handoff_summary": summary,
            "handoff_reason": reason,
        },
    }
    # Side-channel: store for node wrapper to read even if model crashes
    global _pending_routing
    _pending_routing = routing_data["routing"]
    return json.dumps(routing_data)


@tool
def complete_onboarding(
    student_profile: Annotated[str, "The student profile as a JSON string with fields: goal, target_date (ISO date in the FUTURE computed from today + student's timeline, e.g. if student says '4 weeks' and today is 2026-02-13, set to '2026-03-13'), timeline (raw string like '4 weeks' or '3 months'), weekly_hours, skill_level, language, strengths (list), weaknesses (list), learning_style (optional)"],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Complete the onboarding process.

    Call this after gathering all student information through conversation:
    - Goal (FAANG, placements, competitive programming, etc.)
    - Target timeline (e.g., "4 weeks", "3 months") — convert to a FUTURE date for target_date
    - Weekly hours available
    - Skill level (beginner/intermediate/advanced)
    - Preferred coding language
    - Strengths and weaknesses in DSA

    IMPORTANT: target_date must be a FUTURE date. Calculate it as today + the student's timeline.
    Also include the raw 'timeline' string (e.g., "4 weeks", "3 months").

    Pass the student_profile as a JSON string.

    Do NOT create a plan or select a topic — the planning system handles that.
    """
    routing_data = {
        "active_agent": None,
        "onboarding_complete": True,
        "student_profile": student_profile,
        "generate_plan": True,
    }

    files_update = _write_routing(routing_data)

    return Command(
        update={
            "files": files_update,
            "messages": [
                ToolMessage(
                    content=json.dumps({
                        "status": "onboarding_complete",
                        "student_profile": student_profile,
                    }),
                    tool_call_id=tool_call_id,
                )
            ],
        },
    )
