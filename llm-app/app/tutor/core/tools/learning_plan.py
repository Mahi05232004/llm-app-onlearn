"""Learning plan tools — read and update the student's long-term learning plan.

These tools interact directly with MongoDB (always fresh, no caching) so the
agent can check progress, mark topics complete, and adjust the plan.

user_id and module are injected automatically from the agent config —
the agent just calls get_learning_plan() or update_learning_plan(question_id, new_status).
"""

import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import Annotated, Literal

from langchain_core.tools import tool, InjectedToolArg
from langchain_core.runnables import RunnableConfig
from bson import ObjectId

from core.mongo_db import mongo_db_manager

logger = logging.getLogger(__name__)


def _get_db():
    """Get the MongoDB database handle (reuses the singleton connection)."""
    return mongo_db_manager.get_database()


def _sync_plan_to_store(user_id: str, plan_markdown: str) -> None:
    """Write the formatted plan markdown to the StoreBackend as /global_plan.md.

    This is a belt-and-suspenders measure: the agent is instructed to call
    get_learning_plan tool (not read_file), but any legacy or emergent
    read_file('/global_plan.md') calls will now find a fresh copy in the store.
    """
    try:
        from app.tutor.core.store import get_tutor_store
        store = get_tutor_store()
        now = datetime.now(timezone.utc).isoformat()
        file_data = {
            "content": plan_markdown.split("\n"),
            "created_at": now,
            "modified_at": now,
        }
        # Store is async; run in a new event loop if there isn't one already running,
        # otherwise schedule as a fire-and-forget task.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(store.aput((user_id,), "global_plan.md", file_data))
            else:
                loop.run_until_complete(store.aput((user_id,), "global_plan.md", file_data))
        except RuntimeError:
            # Fallback: no event loop available, skip sync
            pass
    except Exception as e:
        logger.debug(f"[LearningPlan] Could not sync /global_plan.md to store: {e}")


def _extract_user_and_module(config: RunnableConfig) -> tuple[str, str]:
    """Extract user_id and module from the agent config.

    Convention: assistant_id = user_id, and module is stored in
    config["configurable"]["module"].
    """
    configurable = config.get("configurable", {})
    user_id = configurable.get("assistant_id", "")
    module = configurable.get("module", "dsa")
    return user_id, module


def _format_plan_as_markdown(plan_dict: dict, module: str) -> str:
    """Format a LearningPlan dict as a readable markdown checklist."""
    weeks = plan_dict.get("weeks", [])
    total_topics = plan_dict.get("total_topics", 0)
    total_weeks = plan_dict.get("total_weeks", len(weeks))

    lines = [
        f"# Learning Plan ({module.upper()})",
        "",
        f"**Total Topics:** {total_topics}",
        f"**Total Weeks:** {total_weeks}",
        "---",
    ]

    for week in weeks:
        week_num = week.get("week_number", "?")
        focus = week.get("focus_area", "")
        status = week.get("status", "not_started")
        lines.append(f"## Week {week_num}: {focus} (Status: {status})")

        for topic in week.get("topics", []):
            topic_status = topic.get("status", "not_started")
            mark = "x" if topic_status == "completed" else " "
            title = topic.get("title", "Untitled")
            difficulty = topic.get("difficulty", "")
            qid = topic.get("question_id", "")
            lines.append(f"- [{mark}] {title} ({difficulty}) [id: {qid}]")

        lines.append("")

    return "\n".join(lines)


@tool
def get_learning_plan(
    config: Annotated[RunnableConfig, InjectedToolArg()],
) -> str:
    """Read the student's current learning plan with full progress status.

    Use this to check what topics the student has completed, what's in progress,
    and what's coming next. Always reads fresh from the database. Call this when
    a session starts, when the student asks about progress, or when you need
    to decide what to teach or recommend.
    """
    user_id, module = _extract_user_and_module(config)
    if not user_id:
        return json.dumps({"status": "error", "message": "No user_id in config."})

    db = _get_db()

    try:
        user = db["users"].find_one(
            {"_id": ObjectId(user_id)},
            {f"modules.{module}.learningPlan": 1},
        )
    except Exception as e:
        logger.error(f"Failed to fetch learning plan: {e}")
        return json.dumps({"status": "error", "message": "Failed to fetch learning plan."})

    if not user:
        return json.dumps({"status": "not_found", "message": "User not found."})

    plan_dict = (user.get("modules") or {}).get(module, {}).get("learningPlan")
    if not plan_dict:
        return json.dumps({"status": "no_plan", "message": "No learning plan exists yet for this module."})

    plan_markdown = _format_plan_as_markdown(plan_dict, module)

    # Write to store so read_file('/global_plan.md') also works as a fallback
    _sync_plan_to_store(user_id, plan_markdown)

    return plan_markdown


@tool(parse_docstring=True)
def update_learning_plan(
    question_id: str,
    new_status: Literal["not_started", "in_progress", "completed"],
    config: Annotated[RunnableConfig, InjectedToolArg()],
) -> str:
    """Update the status of a specific topic in the student's learning plan.

    Use this when the student has completed a topic, started working on one,
    or when you need to adjust progress tracking. Also updates the parent
    week's status automatically.

    Args:
        question_id: The question ID to update (e.g., 'q_1_2_3').
        new_status: The new status for the topic.
    """
    user_id, module = _extract_user_and_module(config)
    if not user_id:
        return json.dumps({"status": "error", "message": "No user_id in config."})

    db = _get_db()
    prefix = f"modules.{module}"

    try:
        user = db["users"].find_one(
            {"_id": ObjectId(user_id)},
            {f"{prefix}.learningPlan": 1},
        )
    except Exception as e:
        logger.error(f"Failed to fetch plan for update: {e}")
        return json.dumps({"status": "error", "message": "Failed to fetch learning plan."})

    if not user:
        return json.dumps({"status": "error", "message": "User not found."})

    plan_dict = (user.get("modules") or {}).get(module, {}).get("learningPlan")
    if not plan_dict:
        return json.dumps({"status": "error", "message": "No learning plan exists."})

    # Find and update the topic
    topic_found = False
    topic_title = ""
    for week in plan_dict.get("weeks", []):
        for topic in week.get("topics", []):
            if topic.get("question_id") == question_id:
                topic["status"] = new_status
                topic_title = topic.get("title", question_id)
                topic_found = True
                break

        if topic_found:
            # Auto-update week status based on topic statuses
            statuses = [t.get("status", "not_started") for t in week.get("topics", [])]
            if all(s == "completed" for s in statuses):
                week["status"] = "completed"
            elif any(s in ("in_progress", "completed") for s in statuses):
                week["status"] = "in_progress"
            break

    if not topic_found:
        return json.dumps({
            "status": "not_found",
            "message": f"Topic with question_id '{question_id}' not found in the plan.",
        })

    # Save updated plan back to MongoDB
    try:
        db["users"].update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {f"{prefix}.learningPlan": plan_dict}},
        )
    except Exception as e:
        logger.error(f"Failed to save plan update: {e}")
        return json.dumps({"status": "error", "message": "Failed to save plan update."})

    result = json.dumps({
        "status": "success",
        "message": f"Updated '{topic_title}' to '{new_status}'.",
        "question_id": question_id,
        "new_status": new_status,
    })

    # Sync updated plan to store as /global_plan.md
    updated_markdown = _format_plan_as_markdown(plan_dict, module)
    _sync_plan_to_store(user_id, updated_markdown)

    return result
