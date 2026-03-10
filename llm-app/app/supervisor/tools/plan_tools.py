"""
Plan tools for the Master Agent.

These tools let the Master Agent interact with the planning system:
- Check if a plan has been generated yet (transition phase)
- Get current progress metrics
- Update the plan based on student requests
"""

from typing import Annotated
from datetime import datetime, UTC
import json
import logging

from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.types import Command

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# File paths in the virtual filesystem
# ──────────────────────────────────────────────

PLAN_FILE = "/plan.json"
PROGRESS_FILE = "/progress.json"
SHORT_TERM_FILE = "/short_term_plan.json"


def _read_file_from_state(state: dict, path: str) -> dict | None:
    """Read a file from the virtual filesystem in state."""
    files = state.get("files", {})
    file_data = files.get(path)
    if file_data is None:
        return None
    if isinstance(file_data, dict) and "content" in file_data:
        try:
            return json.loads(file_data["content"])
        except (json.JSONDecodeError, TypeError):
            return None
    return file_data if isinstance(file_data, dict) else None


@tool
def check_plan_status(
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Check if the student's learning plan has been generated yet.

    Use this during the transition phase after onboarding to check
    if the planner has finished creating the weekly plan. If not ready,
    continue engaging the student in conversation.

    Returns the plan status and summary if available.
    """
    # This tool reads from injected state files.
    # The actual plan data is injected by the stream route from MongoDB.
    # If plan.json exists in files, the plan is ready.
    # If it doesn't, the plan is still being generated.

    # NOTE: This is a "stateless" tool — the actual check happens via
    # the files injected into state. The tool just provides a way for
    # the agent to express "I want to know if the plan is ready" and
    # triggers reading the state files.

    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=(
                        "Check the /plan.json and /progress.json files in your context. "
                        "If they exist and contain data, the plan is ready — present it to the student. "
                        "If they don't exist, the plan is still being generated — keep the student engaged."
                    ),
                    tool_call_id=tool_call_id,
                )
            ],
        },
    )


@tool
def get_student_progress(
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Get the student's current learning progress.

    Use this to check:
    - How many topics they've completed
    - Whether they're ahead, on track, or behind schedule
    - Their estimated completion date
    - Their current streak

    Reference this data naturally in conversation, e.g.:
    "You're 15% through the course and 3 days ahead of schedule! 🔥"
    """
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=(
                        "Read the /progress.json file in your context for the student's "
                        "current progress metrics. Reference the data naturally in your response."
                    ),
                    tool_call_id=tool_call_id,
                )
            ],
        },
    )


@tool
def request_plan_update(
    action: Annotated[str, (
        "The plan update action: "
        "'topic_completed' (student finished a topic), "
        "'off_plan_topic' (student working on unscheduled topic), "
        "'adjust_schedule' (student wants to skip time or extend deadline), "
        "'status_check' (get current progress and short-term plan)"
    )],
    question_id: Annotated[str, (
        "The question_id involved (required for 'topic_completed' and 'off_plan_topic'). "
        "Use '' for 'adjust_schedule' and 'status_check'."
    )],
    details: Annotated[str, (
        "Additional context. For 'adjust_schedule': describe what the student wants, "
        "e.g. 'skip this week', 'busy for 3 days', 'extend deadline by 2 weeks'. "
        "For 'topic_completed': optionally how many minutes the student spent. "
        "For others: brief context."
    )] = "",
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """
    Request a plan update via the internal Planner Agent.

    This tool runs a background planning agent that updates the student's
    learning plan, progress metrics, and short-term plan in the database.

    Use when:
    - A sub-agent hands back with 'objective_complete' → action='topic_completed'
    - The student is working on a topic not in their current week → action='off_plan_topic'
    - The student wants to adjust their schedule → action='adjust_schedule'
    - You want to check current progress → action='status_check'

    The planner will update the plan in the database and return a summary
    you can reference naturally in your response.
    """
    import asyncio
    from app.supervisor.planning.planner_runner import run_planner_agent

    # Build the task description for the planner agent
    task_descriptions = {
        "topic_completed": f"Mark topic {question_id} as completed. {details}".strip(),
        "off_plan_topic": f"The student is working on topic {question_id} which is not in their current week's plan. Absorb it. {details}".strip(),
        "adjust_schedule": f"Adjust the student's schedule: {details}".strip(),
        "status_check": f"Get the student's current progress and short-term plan. {details}".strip(),
    }
    task = task_descriptions.get(action, f"Handle plan update: {action}. {details}")

    # Note: tool_call_id and user_id injection happen at the orchestrator level.
    # The user_id is passed through the state. For now, we store the task
    # and let the node wrapper handle execution with the user_id from state.

    return Command(
        update={
            "files": {
                "/plan_update_request.json": {
                    "content": json.dumps({
                        "action": action,
                        "question_id": question_id,
                        "details": details,
                        "task": task,
                    }),
                    "metadata": {"type": "plan_update_request"},
                }
            },
            "messages": [
                ToolMessage(
                    content=(
                        f"Plan update requested: {action}. "
                        f"The planner agent will process this. "
                        f"Details: {task}"
                    ),
                    tool_call_id=tool_call_id,
                )
            ],
        },
    )


# List of tools to register with the master agent
plan_tools = [check_plan_status, get_student_progress, request_plan_update]

