"""
Test/Debug API endpoints — tracing, flagging, and scenario export.

These endpoints are for development only. They provide:
- GET  /api/test/traces/recent              — Most recent turns (default view)
- GET  /api/test/traces/flagged             — All flagged turns
- GET  /api/test/traces/session/{session_id} — All turns for a session
- POST /api/test/traces/flag                — Flag a turn as a bug
- POST /api/test/traces/export-scenario     — Export a flagged turn as YAML
- POST /api/test/seed-user                  — Create a test user with pre-built plan
- POST /api/test/reset-user                 — Reset plan/progress for a user

Mount this router only in development:
    if os.environ.get("ENABLE_TEST_ENDPOINTS", "0") == "1":
        app.include_router(test_router, prefix="/api/test")
"""
import json
import logging
from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["test"])


# ──────────────────────────────────────────────
# Request Models
# ──────────────────────────────────────────────

class FlagRequest(BaseModel):
    session_id: str
    turn_index: int
    expected_behavior: str
    tags: list[str] = []

class ExportScenarioRequest(BaseModel):
    session_id: str
    turn_index: int
    scenario_name: str = ""

class SeedUserRequest(BaseModel):
    user_id: str
    with_plan: bool = True
    with_progress: bool = True

class ResetUserRequest(BaseModel):
    user_id: str
    keep_profile: bool = True


# ──────────────────────────────────────────────
# Helpers — serialise MongoDB docs for JSON
# ──────────────────────────────────────────────

def _serialise_turns(turns: list[dict]) -> list[dict]:
    """Convert ObjectIds and datetimes to strings for JSON."""
    for turn in turns:
        if "_id" in turn:
            turn["_id"] = str(turn["_id"])
        if "timestamp" in turn and hasattr(turn["timestamp"], "isoformat"):
            turn["timestamp"] = turn["timestamp"].isoformat()
        if "flagged_at" in turn and hasattr(turn["flagged_at"], "isoformat"):
            turn["flagged_at"] = turn["flagged_at"].isoformat()
    return turns


# ──────────────────────────────────────────────
# Trace Endpoints
# (static paths BEFORE path parameters to avoid shadowing)
# ──────────────────────────────────────────────

@router.get("/traces/recent")
async def get_recent_traces(limit: int = 30):
    """Get the most recent traces across all sessions.
    
    This is the default view — shows the latest turns so you
    can see what's happening right now without needing a session ID.
    """
    from tests.supervisor.tracing.tracer import turn_tracer
    turns = turn_tracer.get_recent_turns(limit=limit)
    return {"turns": _serialise_turns(turns), "count": len(turns)}


@router.get("/traces/flagged")
async def get_flagged_turns(session_id: Optional[str] = None, limit: int = 50):
    """Get all flagged turns, optionally filtered by session."""
    from tests.supervisor.tracing.tracer import turn_tracer
    turns = turn_tracer.get_flagged_turns(session_id=session_id, limit=limit)
    return {"flagged_turns": _serialise_turns(turns), "count": len(turns)}


@router.get("/traces/session/{session_id}")
async def get_session_traces(session_id: str):
    """Get all recorded turns for a specific session."""
    from tests.supervisor.tracing.tracer import turn_tracer
    turns = turn_tracer.get_session_turns(session_id)
    return {"session_id": session_id, "turns": _serialise_turns(turns), "count": len(turns)}


@router.post("/traces/flag")
async def flag_turn(request: FlagRequest):
    """Flag a specific turn as a bug with expected behavior.
    
    Example:
        POST /api/test/traces/flag
        {
            "session_id": "abc123",
            "turn_index": 5,
            "expected_behavior": "Should have delegated to concept_tutor",
            "tags": ["routing", "handoff"]
        }
    """
    from tests.supervisor.tracing.tracer import turn_tracer
    success = turn_tracer.flag_turn(
        session_id=request.session_id,
        turn_index=request.turn_index,
        expected_behavior=request.expected_behavior,
        tags=request.tags,
    )
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Turn {request.turn_index} in session {request.session_id} not found",
        )
    return {"status": "flagged", "session_id": request.session_id, "turn_index": request.turn_index}


@router.post("/traces/export-scenario")
async def export_scenario(request: ExportScenarioRequest):
    """Export a flagged turn as a YAML test scenario.
    
    The YAML contains the full input state (files, routing, mode, message)
    so the scenario can be replayed independently.
    """
    import yaml
    from tests.supervisor.tracing.tracer import turn_tracer
    
    turns = turn_tracer.get_session_turns(request.session_id)
    target_turn = None
    for turn in turns:
        if turn.get("turn_index") == request.turn_index:
            target_turn = turn
            break
    
    if not target_turn:
        raise HTTPException(status_code=404, detail="Turn not found")
    
    scenario_name = request.scenario_name or f"scenario_{request.session_id[:8]}_turn{request.turn_index}"
    
    # Build messages: use message_history if available, fall back to just the user message
    input_data = target_turn.get("input", {})
    message_history = input_data.get("message_history", [])
    current_msg = input_data.get("message", "")
    
    # If we have full history, use it (it already includes the current message)
    # Otherwise, fall back to the single message
    if message_history:
        setup_messages = message_history
    else:
        setup_messages = [{"role": "user", "content": current_msg}] if current_msg else []
    
    scenario = {
        "name": scenario_name,
        "description": target_turn.get("flag_comment", "Captured from live session"),
        "captured_from": {
            "session_id": request.session_id,
            "turn_index": request.turn_index,
            "thread_id": target_turn.get("thread_id", ""),
            "timestamp": str(target_turn.get("timestamp", "")),
        },
        "setup": {
            "mode": input_data.get("mode", "learn"),
            "routing": input_data.get("routing", {}),
            "files": input_data.get("files", {}),
            "messages": setup_messages,
            "user_id": target_turn.get("user_id", ""),
        },
        "actual": {
            "agent": target_turn.get("output", {}).get("agent_name", ""),
            "tools_called": target_turn.get("output", {}).get("tools_called", []),
            "tool_events": target_turn.get("output", {}).get("tool_events", []),
            "routing_after": target_turn.get("output", {}).get("routing", {}),
            "files_after": target_turn.get("output", {}).get("files", {}),
            "response": target_turn.get("output", {}).get("response", ""),
        },
        "expect": {
            "comment": target_turn.get("flag_comment", "TODO: define expected behavior"),
        },
    }
    
    yaml_str = yaml.dump(scenario, default_flow_style=False, sort_keys=False, allow_unicode=True)
    
    return {
        "scenario_name": scenario_name,
        "yaml": yaml_str,
        "save_to": f"tests/supervisor/scenarios/captured/{scenario_name}.yaml",
    }


# ──────────────────────────────────────────────
# Seed & Reset Endpoints
# ──────────────────────────────────────────────

@router.post("/seed-user")
async def seed_user(request: SeedUserRequest):
    """Create or update a test user with a pre-built plan.
    
    Useful for testing without going through onboarding every time.
    """
    from core.mongo_db import MongoDatabaseManager
    
    db = MongoDatabaseManager().get_database()
    collection = db["users"]
    
    user_data: dict = {
        "studentProfile": {
            "goal": "Get better at DSA for interviews",
            "experience": "intermediate",
            "weekly_hours": 10,
            "preferred_difficulty": "medium",
            "language": "Python",
        },
        "isOnboarded": True,
    }
    
    if request.with_plan:
        user_data["learningPlan"] = {
            "weeks": [
                {
                    "week_number": 1,
                    "focus_area": "Arrays & Hashing",
                    "topics": [
                        {"question_id": "two-sum", "title": "Two Sum", "difficulty": "easy", "status": "not_started", "estimated_minutes": 30},
                        {"question_id": "valid-anagram", "title": "Valid Anagram", "difficulty": "easy", "status": "not_started", "estimated_minutes": 30},
                        {"question_id": "group-anagrams", "title": "Group Anagrams", "difficulty": "medium", "status": "not_started", "estimated_minutes": 45},
                    ],
                },
                {
                    "week_number": 2,
                    "focus_area": "Two Pointers",
                    "topics": [
                        {"question_id": "valid-palindrome", "title": "Valid Palindrome", "difficulty": "easy", "status": "not_started", "estimated_minutes": 30},
                        {"question_id": "3sum", "title": "3Sum", "difficulty": "medium", "status": "not_started", "estimated_minutes": 45},
                        {"question_id": "container-with-most-water", "title": "Container With Most Water", "difficulty": "medium", "status": "not_started", "estimated_minutes": 45},
                    ],
                },
                {
                    "week_number": 3,
                    "focus_area": "Binary Search",
                    "topics": [
                        {"question_id": "binary-search", "title": "Binary Search", "difficulty": "easy", "status": "not_started", "estimated_minutes": 30},
                        {"question_id": "search-in-rotated-sorted-array", "title": "Search in Rotated Sorted Array", "difficulty": "medium", "status": "not_started", "estimated_minutes": 45},
                        {"question_id": "find-minimum-in-rotated-sorted-array", "title": "Find Min in Rotated Sorted Array", "difficulty": "medium", "status": "not_started", "estimated_minutes": 45},
                    ],
                },
            ],
            "total_weeks": 3,
            "total_topics": 9,
        }
    
    if request.with_progress:
        user_data["progress"] = {
            "completed_topics": 0,
            "total_topics": 9,
            "completion_percentage": 0.0,
            "current_week": 1,
            "pace": "on_track",
        }
        user_data["shortTermPlan"] = {
            "current_week": 1,
            "current_focus": "Arrays & Hashing",
            "week_progress": "0/3 topics done",
            "next_topics": [
                {"question_id": "two-sum", "title": "Two Sum", "difficulty": "easy", "week": 1},
                {"question_id": "valid-anagram", "title": "Valid Anagram", "difficulty": "easy", "week": 1},
                {"question_id": "group-anagrams", "title": "Group Anagrams", "difficulty": "medium", "week": 1},
            ],
        }
    
    from bson import ObjectId
    try:
        obj_id = ObjectId(request.user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user_id format (must be a valid ObjectId)")
    
    result = collection.update_one(
        {"_id": obj_id},
        {"$set": user_data},
        upsert=True,
    )
    
    return {
        "status": "seeded",
        "user_id": request.user_id,
        "upserted": result.upserted_id is not None,
        "plan_topics": 9 if request.with_plan else 0,
    }


@router.post("/reset-user")
async def reset_user(request: ResetUserRequest):
    """Reset plan, progress, and chat data for a user.
    
    Optionally keep the student profile (so you don't need to re-onboard).
    """
    from core.mongo_db import MongoDatabaseManager
    from bson import ObjectId
    
    db = MongoDatabaseManager().get_database()
    
    try:
        obj_id = ObjectId(request.user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user_id format")
    
    unset_fields = {
        "learningPlan": "",
        "progress": "",
        "shortTermPlan": "",
    }
    if not request.keep_profile:
        unset_fields["studentProfile"] = ""
        unset_fields["isOnboarded"] = ""
    
    # Reset user document
    db["users"].update_one(
        {"_id": obj_id},
        {"$unset": unset_fields},
    )
    
    # Clear chat sessions for this user
    db["chatsessions"].delete_many({"userId": obj_id})
    
    return {
        "status": "reset",
        "user_id": request.user_id,
        "kept_profile": request.keep_profile,
    }
