"""
Planner Agent runner.

Creates and invokes the internal Planner Agent (flash model) with
the student's current plan data. The Master Agent calls this via
the `request_plan_update` tool.

Flow:
1. Read plan data from MongoDB
2. Create planner tools (with plan data as closure)
3. Create agent (flash model + planner prompt + tools)
4. Invoke agent with the task description
5. Write updated plan data back to MongoDB
6. Return summary string for Master
"""

import json
import logging
from datetime import datetime, UTC
from typing import Any

from app.supervisor.agents.base import create_agent
from app.supervisor.config.settings import get_model
from app.supervisor.planning.plan_store import plan_store
from app.supervisor.planning.planner_prompt import PLANNER_AGENT_PROMPT
from app.supervisor.planning.planner_tools import create_planner_tools
from app.supervisor.planning.service import PlanningService

logger = logging.getLogger(__name__)

# Cached planning service instance
_planning_service = PlanningService()


async def run_planner_agent(
    user_id: str,
    task: str,
) -> str:
    """Run the internal Planner Agent to update the student's plan.

    Args:
        user_id: MongoDB user ID
        task: Description of what needs to be done, e.g.
              "Mark topic q_1_2_3 as completed"
              "Student is working on topic q_3_1_2 which is off-plan"
              "Student wants to skip this week"

    Returns:
        Summary string of what was updated, suitable for the Master
        Agent to reference in its response to the student.
    """
    # 1. Read current plan data from MongoDB
    raw_data = plan_store.get_plan_data(user_id)

    if not raw_data or not raw_data.get("learningPlan"):
        return "No learning plan found for this student. Plan needs to be generated first."

    if not raw_data.get("studentProfile"):
        return "No student profile found. Cannot update plan without a profile."

    # Parse started_at
    started_at_raw = raw_data.get("planStartedAt")
    if isinstance(started_at_raw, datetime):
        started_at = started_at_raw
    elif isinstance(started_at_raw, str):
        started_at = datetime.fromisoformat(started_at_raw)
    else:
        started_at = datetime.now(UTC)

    # 2. Create mutable plan data dict (tools mutate this in-place)
    plan_data: dict[str, Any] = {
        "plan": raw_data["learningPlan"],
        "profile": raw_data["studentProfile"],
        "started_at": started_at,
        "progress": raw_data.get("progress", {}),
        "short_term": raw_data.get("shortTermPlan", {}),
    }

    # 3. Create tools with closure over plan_data
    tools = create_planner_tools(plan_data, _planning_service)

    # 4. Create the planner agent (flash model for speed/cost)
    model = get_model(model_type="flash")
    planner_agent = create_agent(model, PLANNER_AGENT_PROMPT, tools)

    # 5. Invoke the agent
    try:
        result = await planner_agent.ainvoke({
            "messages": [("user", task)],
        })

        # Extract the final AI message as the summary
        messages = result.get("messages", [])
        summary = "Plan update completed."
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content and not hasattr(msg, "tool_call_id"):
                summary = msg.content
                break

    except Exception as e:
        logger.error(f"Planner agent failed for user {user_id}: {e}", exc_info=True)
        summary = f"Plan update encountered an error: {str(e)}"

    # 6. Write updated plan data back to MongoDB
    plan_store.save_plan_data(
        user_id=user_id,
        plan=plan_data.get("plan"),
        progress=plan_data.get("progress"),
        short_term=plan_data.get("short_term"),
    )

    logger.info(f"Planner agent completed for user {user_id}: {summary[:100]}...")

    return summary
