"""
FastAPI endpoints for the planning system.

Provides API routes for:
- Generating initial learning plans (triggered after onboarding)
- Retrieving plan and progress data
- Marking topics as completed

All plan data is stored in MongoDB via PlanStore (single source of truth).
"""

import asyncio
import json
import logging
from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.plan_models import StudentProfile, LearningPlan, Progress
from app.supervisor.planning.service import PlanningService
from app.supervisor.planning.plan_store import plan_store

logger = logging.getLogger(__name__)

router = APIRouter()
planning_service = PlanningService()

# In-memory store for plan generation status (per user)
# In production, this would be in Redis or similar
_plan_generation_status: dict[str, str] = {}  # user_id -> "pending" | "generating" | "done" | "error"


# ──────────────────────────────────────────────
# Request/Response Models
# ──────────────────────────────────────────────

class GeneratePlanRequest(BaseModel):
    user_id: str
    student_profile: dict  # Structured profile from onboarding
    feedback: Optional[str] = None  # Student's revision request
    course_id: str = "dsa"  # 'dsa' or 'ds' — determines which curriculum to use

class CompletionRequest(BaseModel):
    question_id: str
    actual_minutes: Optional[int] = None

class PlanResponse(BaseModel):
    plan: dict
    progress: dict
    short_term: dict

class PlanStatusResponse(BaseModel):
    status: str  # "pending" | "generating" | "done" | "error"
    message: str


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@router.post("/generate")
async def generate_plan(request: GeneratePlanRequest):
    """
    Trigger plan generation for a user.

    Called after onboarding completes. Runs the LLM planner + rule-based
    builder asynchronously and stores the result in MongoDB.
    """
    user_id = request.user_id

    # Don't generate if already in progress
    if _plan_generation_status.get(user_id) == "generating":
        return {"status": "generating", "message": "Plan generation already in progress"}

    _plan_generation_status[user_id] = "generating"

    try:
        profile = StudentProfile(**request.student_profile)

        # Run plan generation (this calls the LLM planner)
        started_at = datetime.now(UTC)
        plan, progress = await planning_service.generate_initial_plan(
            profile, started_at, feedback=request.feedback, course_id=request.course_id
        )
        short_term = planning_service.get_short_term_summary(plan)

        # Persist to MongoDB
        plan_store.save_plan_data(
            user_id=user_id,
            plan=plan.model_dump(mode="json"),
            progress=progress.model_dump(mode="json"),
            short_term=short_term,
        )

        _plan_generation_status[user_id] = "done"

        logger.info(
            f"Plan generated for user {user_id}: "
            f"{plan.total_topics} topics, {plan.total_weeks} weeks"
        )

        return {
            "status": "done",
            "plan": plan.model_dump(mode="json"),
            "progress": progress.model_dump(mode="json"),
            "short_term": short_term,
        }

    except Exception as e:
        _plan_generation_status[user_id] = "error"
        logger.error(f"Plan generation failed for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Plan generation failed: {str(e)}")


@router.get("/status/{user_id}")
async def get_plan_status(user_id: str):
    """Check if plan generation is complete."""
    status = _plan_generation_status.get(user_id, "pending")
    messages = {
        "pending": "No plan generation has been requested",
        "generating": "Plan is being generated...",
        "done": "Plan is ready",
        "error": "Plan generation encountered an error",
    }
    return PlanStatusResponse(status=status, message=messages.get(status, "Unknown"))


@router.get("/{user_id}")
async def get_plan(user_id: str):
    """Get the current plan for a user from MongoDB."""
    data = plan_store.get_plan_data(user_id)
    if not data or not data.get("learningPlan"):
        raise HTTPException(status_code=404, detail="No plan found for this user")

    return PlanResponse(
        plan=data["learningPlan"],
        progress=data.get("progress", {}),
        short_term=data.get("shortTermPlan", {}),
    )


@router.get("/{user_id}/progress")
async def get_progress(user_id: str):
    """Get just the progress metrics for a user (lightweight endpoint for the progress bar)."""
    data = plan_store.get_plan_data(user_id)
    if not data or not data.get("progress"):
        raise HTTPException(status_code=404, detail="No plan found for this user")

    return data["progress"]


@router.post("/{user_id}/complete-topic")
async def complete_topic(user_id: str, request: CompletionRequest):
    """
    Mark a topic as completed and recalculate plan + progress.

    Called when a student finishes working on a question.
    """
    data = plan_store.get_plan_data(user_id)
    if not data or not data.get("learningPlan"):
        raise HTTPException(status_code=404, detail="No plan found for this user")

    try:
        plan = LearningPlan(**data["learningPlan"])
        profile = StudentProfile(**data["studentProfile"])
        started_at = data.get("planStartedAt") or datetime.now(UTC)
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)

        plan, progress = planning_service.complete_topic(
            plan, profile, request.question_id, started_at, request.actual_minutes
        )
        short_term = planning_service.get_short_term_summary(plan)

        # Persist to MongoDB
        plan_store.save_plan_data(
            user_id=user_id,
            plan=plan.model_dump(mode="json"),
            progress=progress.model_dump(mode="json"),
            short_term=short_term,
        )

        return {
            "status": "updated",
            "progress": progress.model_dump(mode="json"),
            "short_term": short_term,
        }

    except Exception as e:
        logger.error(f"Failed to complete topic for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{user_id}/off-plan")
async def handle_off_plan(user_id: str, request: CompletionRequest):
    """
    Handle a student starting a topic not in their current week.

    Called when the frontend detects the student opened a topic
    that's not in their current week's plan AND sent their first message.
    """
    data = plan_store.get_plan_data(user_id)
    if not data or not data.get("learningPlan"):
        raise HTTPException(status_code=404, detail="No plan found for this user")

    try:
        plan = LearningPlan(**data["learningPlan"])
        profile = StudentProfile(**data["studentProfile"])
        started_at = data.get("planStartedAt") or datetime.now(UTC)
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)

        plan, progress = planning_service.handle_off_plan_topic(
            plan, profile, request.question_id, started_at
        )
        short_term = planning_service.get_short_term_summary(plan)

        # Persist to MongoDB
        plan_store.save_plan_data(
            user_id=user_id,
            plan=plan.model_dump(mode="json"),
            progress=progress.model_dump(mode="json"),
            short_term=short_term,
        )

        return {
            "status": "updated",
            "plan": plan.model_dump(mode="json"),
            "progress": progress.model_dump(mode="json"),
            "short_term": short_term,
        }

    except Exception as e:
        logger.error(f"Failed to handle off-plan topic for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
