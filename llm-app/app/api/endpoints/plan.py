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
from datetime import datetime, UTC, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.models.plan_models import StudentProfile, LearningPlan, Progress
from app.planning.service import PlanningService
from app.planning.plan_store import plan_store

logger = logging.getLogger(__name__)

router = APIRouter()
planning_service = PlanningService()

# In-memory store for plan generation status (per user)
# In production, this would be in Redis or similar
_plan_generation_status: dict[str, dict] = {}  # user_id -> {"status": ..., "started_at": ...}

# How long before a "generating" status is considered stale (gateway timeout, etc.)
_GENERATING_TIMEOUT_SECONDS = 120


def _get_plan_status(user_id: str) -> str:
    """Get the current plan generation status, auto-clearing stale entries."""
    entry = _plan_generation_status.get(user_id)
    if not entry:
        return "pending"
    status = entry.get("status", "pending")
    if status == "generating":
        started = entry.get("started_at")
        if started and (datetime.now(UTC) - started).total_seconds() > _GENERATING_TIMEOUT_SECONDS:
            logger.warning(f"[Plan] Stale 'generating' status for user={user_id}, clearing")
            _plan_generation_status[user_id] = {"status": "error", "started_at": started}
            return "error"
    return status


def _set_plan_status(user_id: str, status: str) -> None:
    """Set plan generation status with timestamp."""
    _plan_generation_status[user_id] = {"status": status, "started_at": datetime.now(UTC)}


# ──────────────────────────────────────────────
# Request/Response Models
# ──────────────────────────────────────────────

class GeneratePlanRequest(BaseModel):
    user_id: str
    student_profile: dict  # Structured profile from onboarding
    module: str = "dsa"  # Learning module ('dsa', 'ds', etc.)
    feedback: Optional[str] = None  # Student's revision request

class GenerateDefaultPlanRequest(BaseModel):
    user_id: str
    module: str = "dsa"

class CompletionRequest(BaseModel):
    question_id: str
    actual_minutes: Optional[int] = None


# ──────────────────────────────────────────────
# Default Plan Builder (reusable helper)
# ──────────────────────────────────────────────

def build_default_plan(module: str) -> dict:
    """Build a default learning plan from the course sidebar ordering.

    Returns a plan dict with the same structure as personalized plans:
    { weeks: [...], total_topics, total_weeks, ... }

    This is a pure function — no DB writes. Used by:
    - generate_default_plan endpoint (saves to DB)
    - orchestrator fallback (saves to DB separately)
    """
    from core.course_data import get_sidebar_data
    from datetime import timedelta

    WEEKLY_MINUTES = 720          # 12 hours per week
    DIFFICULTY_MINUTES = {
        "easy": 30,
        "medium": 45,
        "hard": 60,
    }
    DEFAULT_LANGUAGE = "cpp" if module == "dsa" else "python"

    sidebar = get_sidebar_data(course_id=module)

    # ── Step 1: Flatten all questions preserving sidebar order ──────────
    all_topics: list[dict] = []
    for step in sidebar:
        step_title = step.get("title", "")
        for sub in step.get("sub_steps", []):
            for q in sub.get("questions", []):
                qid = q.get("question_id", "")
                if not qid:
                    continue
                title = q.get("question_title") or q.get("title") or "Unknown"
                difficulty = (q.get("difficulty") or "easy").lower()
                if difficulty not in DIFFICULTY_MINUTES:
                    difficulty = "easy"
                all_topics.append({
                    "question_id": qid,
                    "title": title,
                    "difficulty": difficulty,
                    "estimated_minutes": DIFFICULTY_MINUTES[difficulty],
                    "status": "not_started",
                    "_section": step_title,   # used for week naming, stripped before save
                })

    if not all_topics:
        return {}

    # ── Step 2: Greedy bin-pack into 720-minute weeks ───────────────────
    now = datetime.now(UTC)
    weeks = []
    week_number = 1
    i = 0

    while i < len(all_topics):
        bucket_minutes = 0
        bucket_topics = []
        section_counter: dict[str, int] = {}

        while i < len(all_topics):
            topic = all_topics[i]
            cost = topic["estimated_minutes"]
            if bucket_minutes + cost > WEEKLY_MINUTES and bucket_topics:
                break
            section_counter[topic["_section"]] = section_counter.get(topic["_section"], 0) + 1
            bucket_topics.append({k: v for k, v in topic.items() if k != "_section"})
            bucket_minutes += cost
            i += 1

        focus_area = max(section_counter, key=lambda s: section_counter[s])

        start = now + timedelta(weeks=week_number - 1)
        end = start + timedelta(days=6)

        weeks.append({
            "week_number": week_number,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "focus_area": focus_area,
            "planned_minutes": bucket_minutes,
            "buffer_minutes": max(0, WEEKLY_MINUTES - bucket_minutes),
            "topics": bucket_topics,
            "status": "not_started",
        })
        week_number += 1

    # ── Step 3: Build plan object ───────────────────────────────────────
    total_topics = len(all_topics)
    total_minutes = sum(t["estimated_minutes"] for t in all_topics)

    return {
        "weeks": weeks,
        "total_topics": total_topics,
        "total_weeks": len(weeks),
        "total_estimated_minutes": total_minutes,
        "weekly_hours": 12,
        "default_language": DEFAULT_LANGUAGE,
        "plan_version": 1,
        "is_default": True,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }


# ──────────────────────────────────────────────
# Generate Default Plan Endpoint
# ──────────────────────────────────────────────

@router.post("/generate-default")
async def generate_default_plan(request: GenerateDefaultPlanRequest):
    """
    Generate an instant default learning plan without LLM personalization.
    Uses build_default_plan() helper and saves to MongoDB.
    """
    user_id = request.user_id
    module = request.module

    try:
        plan = build_default_plan(module)
    except Exception as e:
        logger.error(f"[DefaultPlan] Could not load course data for module={module}: {e}")
        raise HTTPException(status_code=500, detail="Failed to load course data.")

    if not plan:
        raise HTTPException(status_code=500, detail="No questions found in course data.")

    first_question_id = plan["weeks"][0]["topics"][0]["question_id"] if plan.get("weeks") else None

    progress = {
        "total_topics": plan.get("total_topics", 0),
        "completed_topics": 0,
        "completion_percentage": 0.0,
        "days_remaining": plan.get("total_weeks", 0) * 7,
        "estimated_completion": (datetime.now(UTC) + timedelta(weeks=plan.get("total_weeks", 0))).isoformat(),
        "pace_status": "on_track",
        "pace_message": "Just getting started!",
    }

    saved = plan_store.save_plan_data(
        user_id=user_id,
        module=module,
        plan=plan,
        progress=progress,
        status="done",
    )

    if not saved:
        raise HTTPException(status_code=500, detail="Failed to save default plan.")

    logger.info(
        f"[DefaultPlan] Generated for user={user_id}, module={module}, "
        f"topics={plan.get('total_topics')}, weeks={plan.get('total_weeks')}"
    )

    return {
        "status": "done",
        "plan": plan,
        "progress": progress,
        "first_question_id": first_question_id,
    }


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
    if _get_plan_status(user_id) == "generating":
        return {"status": "generating", "message": "Plan generation already in progress"}

    _set_plan_status(user_id, "generating")

    try:
        profile = StudentProfile(**request.student_profile)

        # Run plan generation (this calls the LLM planner)
        started_at = datetime.now(UTC)
        plan, progress = await planning_service.generate_initial_plan(
            profile, course_id=request.module, started_at=started_at, feedback=request.feedback, user_id=user_id
        )
        short_term = planning_service.get_short_term_summary(plan)

        # Persist to MongoDB (module-aware)
        plan_store.save_plan_data(
            user_id=user_id,
            module=request.module,
            plan=plan.model_dump(mode="json"),
            progress=progress.model_dump(mode="json"),
            short_term=short_term,
            status="done",
        )

        _set_plan_status(user_id, "done")

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
        _set_plan_status(user_id, "error")
        logger.error(f"Plan generation failed for user {user_id}: {e}", exc_info=True)
        try:
            plan_store.save_plan_data(user_id=user_id, module=request.module, status="error")
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Plan generation failed: {str(e)}")

@router.post("/generate/stream")
async def generate_plan_stream(request: GeneratePlanRequest):
    """
    Trigger plan generation for a user and stream tokens via Server-Sent Events (SSE).
    """
    user_id = request.user_id

    # Block only if genuinely in-progress (not stale/timed-out)
    if _get_plan_status(user_id) == "generating":
        raise HTTPException(status_code=409, detail="Plan generation already in progress")

    _set_plan_status(user_id, "generating")

    async def event_generator():
        try:
            profile = StudentProfile(**request.student_profile)
            started_at = datetime.now(UTC)
            
            # Use the streaming service
            async for chunk in planning_service.stream_initial_plan(
                profile, course_id=request.module, started_at=started_at, feedback=request.feedback, user_id=user_id
            ):
                if isinstance(chunk, str):
                    # It's a raw string token from the LLM
                    # Format as Server-Sent Event (SSE)
                    safe_token = chunk.replace('\n', '\\n').replace('"', '\\"') # minimal escape
                    yield f'data: {{"type": "token", "content": "{safe_token}"}}\n\n'
                
                elif isinstance(chunk, dict) and "plan" in chunk:
                    # Final result dictionary generated by builder
                    plan = chunk["plan"]
                    progress = chunk["progress"]
                    short_term = planning_service.get_short_term_summary(plan)

                    # Persist to MongoDB (module-aware)
                    plan_store.save_plan_data(
                        user_id=user_id,
                        module=request.module,
                        plan=plan.model_dump(mode="json"),
                        progress=progress.model_dump(mode="json"),
                        short_term=short_term,
                        status="done",
                    )

                    _set_plan_status(user_id, "done")
                    
                    final_payload = {
                        "type": "done",
                        "plan": plan.model_dump(mode="json"),
                        "progress": progress.model_dump(mode="json"),
                        "short_term": short_term,
                    }
                    yield f'data: {json.dumps(final_payload)}\n\n'
                    
            # After returning, close stream
            return

        except Exception as e:
            _set_plan_status(user_id, "error")
            logger.error(f"Plan stream generation failed for user {user_id}: {e}", exc_info=True)
            try:
                plan_store.save_plan_data(user_id=user_id, module=request.module, status="error")
            except:
                pass
            yield f'data: {json.dumps({"type": "error", "message": "Something went wrong generating your plan. Please tap retry.", "canRetry": True})}\n\n'

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/status/{user_id}")
async def get_plan_status(user_id: str):
    """Check if plan generation is complete."""
    status = _get_plan_status(user_id)
    messages = {
        "pending": "No plan generation has been requested",
        "generating": "Plan is being generated...",
        "done": "Plan is ready",
        "error": "Plan generation encountered an error",
    }
    return PlanStatusResponse(status=status, message=messages.get(status, "Unknown"))


@router.get("/{user_id}")
async def get_plan(user_id: str, module: str = "dsa"):
    """Get the current plan for a user from MongoDB."""
    data = plan_store.get_plan_data(user_id, module=module)
    if not data or not data.get("learningPlan"):
        raise HTTPException(status_code=404, detail="No plan found for this user")

    return PlanResponse(
        plan=data["learningPlan"],
        progress=data.get("progress", {}),
        short_term=data.get("shortTermPlan", {}),
    )


@router.get("/{user_id}/progress")
async def get_progress(user_id: str, module: str = "dsa"):
    """Get just the progress metrics for a user (lightweight endpoint for the progress bar)."""
    data = plan_store.get_plan_data(user_id, module=module)
    if not data or not data.get("progress"):
        raise HTTPException(status_code=404, detail="No plan found for this user")

    return data["progress"]


@router.post("/{user_id}/complete-topic")
async def complete_topic(user_id: str, request: CompletionRequest, module: str = "dsa"):
    """
    Mark a topic as completed and recalculate plan + progress.

    Called when a student finishes working on a question.
    """
    data = plan_store.get_plan_data(user_id, module=module)
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

        # Persist to MongoDB (module-aware)
        plan_store.save_plan_data(
            user_id=user_id,
            module=module,
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
async def handle_off_plan(user_id: str, request: CompletionRequest, module: str = "dsa"):
    """
    Handle a student starting a topic not in their current week.

    Called when the frontend detects the student opened a topic
    that's not in their current week's plan AND sent their first message.
    """
    data = plan_store.get_plan_data(user_id, module=module)
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

        # Persist to MongoDB (module-aware)
        plan_store.save_plan_data(
            user_id=user_id,
            module=module,
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


@router.get("/{user_id}/next-question")
async def get_next_question(user_id: str, module: str = "dsa"):
    """
    Get the first not-started topic from the user's learning plan.

    Iterates weeks in order and returns the first topic with status='not_started'.
    Returns 404 if no incomplete topics remain (plan fully complete).
    """
    data = plan_store.get_plan_data(user_id, module=module)
    if not data or not data.get("learningPlan"):
        raise HTTPException(status_code=404, detail="No plan found for this user")

    try:
        plan = LearningPlan(**data["learningPlan"])
    except Exception as e:
        logger.error(f"Failed to parse plan for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Plan data is malformed")

    from app.models.plan_models import TopicStatus

    for week in plan.weeks:
        for topic in week.topics:
            if topic.status == TopicStatus.NOT_STARTED:
                return {
                    "question_id": topic.question_id,
                    "title": topic.title,
                    "difficulty": topic.difficulty,
                    "week_number": week.week_number,
                }

    # All topics complete
    raise HTTPException(status_code=404, detail="All topics in the plan are complete")

