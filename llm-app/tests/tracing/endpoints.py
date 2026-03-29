"""
Test/Debug API endpoints — tracing, flagging, annotation, and scenario export.

These endpoints are for development only. They provide:
- GET  /api/test/traces/recent              — Most recent turns (default view)
- GET  /api/test/traces/flagged             — All flagged eval cases
- GET  /api/test/traces/session/{session_id} — All turns for a session
- POST /api/test/traces/flag                — Flag a turn (copy to eval_cases)
- POST /api/test/traces/flag-by-id          — Flag a turn by trace _id (preferred)
- DELETE /api/test/traces/flag              — Delete a flagged eval case
- POST /api/test/traces/eval-lightweight    — Run eval on a single case
- POST /api/test/traces/eval-lightweight-all — Run evals on all pending cases
- POST /api/test/traces/export-scenario     — Export a trace as YAML
- POST /api/test/eval-cases                 — Create a manual eval case (plan-review)
- PATCH /api/test/eval-cases/{id}/status    — Update eval case status
- GET  /api/test/eval-runs                  — List eval run history
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

class FlagByIdRequest(BaseModel):
    trace_id: str
    expected_behavior: str
    tags: list[str] = []

class ManualEvalCaseRequest(BaseModel):
    """Create an eval case directly (for plan-review, etc.)."""
    input_data: dict = {}
    output_data: dict = {}
    flag_comment: str
    tags: list[str] = []
    agent_type: str = "plan_generator"
    module: str = "dsa"
    session_id: str = ""
    user_id: str = ""

class UpdateCaseStatusRequest(BaseModel):
    status: str  # "pending" | "fixed" | "wont_fix"

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

class ReplayRequest(BaseModel):
    """Run replay eval on a single eval case."""
    case_id: str  # eval_case _id

class ReplayBySessionRequest(BaseModel):
    """Run replay eval by session_id + turn_index (backward compat)."""
    session_id: str
    turn_index: int

class ReplayAllRequest(BaseModel):
    """Run replay eval on all pending eval cases."""
    agent_type: str | None = None
    limit: int = 50


# ──────────────────────────────────────────────
# Helpers — serialise MongoDB docs for JSON
# ──────────────────────────────────────────────

def _serialise_docs(docs: list[dict]) -> list[dict]:
    """Convert ObjectIds and datetimes to strings for JSON."""
    for doc in docs:
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        for field in ("timestamp", "flagged_at", "created_at", "original_timestamp", "status_updated_at"):
            if field in doc and hasattr(doc[field], "isoformat"):
                doc[field] = doc[field].isoformat()
    return docs


# ──────────────────────────────────────────────
# Trace Endpoints (read-only view of ephemeral traces)
# ──────────────────────────────────────────────

@router.get("/traces/recent")
async def get_recent_traces(limit: int = 30):
    """Get the most recent traces across all sessions."""
    from tests.tracing.tracer import turn_tracer
    turns = turn_tracer.get_recent_turns(limit=limit)
    return {"turns": _serialise_docs(turns), "count": len(turns)}


@router.get("/traces/session/{session_id}")
async def get_session_traces(session_id: str):
    """Get all recorded turns for a specific session."""
    from tests.tracing.tracer import turn_tracer
    turns = turn_tracer.get_session_turns(session_id)
    return {"session_id": session_id, "turns": _serialise_docs(turns), "count": len(turns)}


# ──────────────────────────────────────────────
# Flag Endpoints (copy trace → eval_cases)
# ──────────────────────────────────────────────

@router.get("/traces/flagged")
async def get_flagged_cases(
    agent_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
):
    """Get all flagged eval cases (reads from eval_cases collection)."""
    from tests.tracing.eval_store import eval_case_manager
    cases = eval_case_manager.get_eval_cases(
        status=status, agent_type=agent_type, limit=limit
    )
    return {"flagged_turns": _serialise_docs(cases), "count": len(cases)}


@router.post("/traces/flag")
async def flag_turn(request: FlagRequest):
    """Flag a turn by session_id + turn_index.

    Looks up the trace from the ephemeral traces collection, then copies
    the full document to the permanent eval_cases collection.
    Will NOT create stubs — returns 404 if trace doesn't exist.
    """
    from tests.tracing.eval_store import eval_case_manager

    result = eval_case_manager.flag_by_session(
        session_id=request.session_id,
        turn_index=request.turn_index,
        expected_behavior=request.expected_behavior,
        tags=request.tags,
    )

    if result["status"] == "flagged":
        return {"status": "flagged", "case_id": result["case_id"]}
    elif result["status"] == "duplicate":
        return {"status": "already_flagged", "case_id": result.get("case_id"), "detail": result["detail"]}
    else:
        raise HTTPException(status_code=404, detail=result.get("detail", "Flag failed"))


@router.post("/traces/flag-by-id")
async def flag_trace_by_id(request: FlagByIdRequest):
    """Flag a trace by its MongoDB _id (preferred method).

    Copies the full trace document to eval_cases.
    """
    from tests.tracing.eval_store import eval_case_manager

    result = eval_case_manager.flag_trace(
        trace_id=request.trace_id,
        expected_behavior=request.expected_behavior,
        tags=request.tags,
    )

    if result["status"] == "flagged":
        return {"status": "flagged", "case_id": result["case_id"]}
    elif result["status"] == "duplicate":
        return {"status": "already_flagged", "case_id": result.get("case_id"), "detail": result["detail"]}
    else:
        raise HTTPException(
            status_code=404 if "not found" in result.get("detail", "").lower() else 400,
            detail=result.get("detail", "Flag failed"),
        )


@router.delete("/traces/flag")
async def delete_flagged_case(session_id: str, turn_index: int):
    """Delete a flagged eval case."""
    from tests.tracing.eval_store import eval_case_manager
    success = eval_case_manager.delete_eval_case_by_session(session_id, turn_index)
    if not success:
        raise HTTPException(status_code=404, detail="Eval case not found")
    return {"status": "deleted", "session_id": session_id, "turn_index": turn_index}


# ──────────────────────────────────────────────
# Manual Eval Cases (plan-review, etc.)
# ──────────────────────────────────────────────

@router.post("/eval-cases")
async def create_manual_eval_case(request: ManualEvalCaseRequest):
    """Create an eval case directly without a source trace.

    Used for plan-review flags and other flows that don't go through
    the chat orchestrator.
    """
    from tests.tracing.eval_store import eval_case_manager

    result = eval_case_manager.create_manual_case(
        input_data=request.input_data,
        output_data=request.output_data,
        flag_comment=request.flag_comment,
        tags=request.tags,
        agent_type=request.agent_type,
        module=request.module,
        session_id=request.session_id,
        user_id=request.user_id,
    )

    if result["status"] == "flagged":
        return {"status": "created", "case_id": result["case_id"]}
    else:
        raise HTTPException(status_code=400, detail=result.get("detail", "Failed"))


@router.patch("/eval-cases/{case_id}/status")
async def update_eval_case_status(case_id: str, request: UpdateCaseStatusRequest):
    """Update the status of an eval case (pending → fixed | wont_fix)."""
    from tests.tracing.eval_store import eval_case_manager

    if request.status not in ("pending", "fixed", "wont_fix"):
        raise HTTPException(status_code=400, detail="Status must be: pending, fixed, or wont_fix")

    success = eval_case_manager.update_case_status(case_id, request.status)
    if not success:
        raise HTTPException(status_code=404, detail="Eval case not found")
    return {"status": "updated", "case_id": case_id, "new_status": request.status}


# ──────────────────────────────────────────────
# Eval Endpoints
# ──────────────────────────────────────────────

@router.post("/traces/eval-lightweight")
async def eval_lightweight(request: ReplayBySessionRequest):
    """Evaluate a single flagged trace by re-prompting the agent and judging."""
    import asyncio
    from tests.tracing.eval_store import eval_case_manager
    from tests.agentic.evals.replay_runner import re_prompt_trace
    from tests.agentic.evals.judge import Judge

    # Find the eval case by session_id + turn_index
    cases = eval_case_manager.get_eval_cases()
    target_case = next(
        (c for c in cases
         if c.get("session_id") == request.session_id
         and c.get("turn_index") == request.turn_index),
        None,
    )
    if not target_case:
        raise HTTPException(status_code=404, detail="Eval case not found")

    # Re-prompt with timeout
    try:
        replay_result = await asyncio.wait_for(
            re_prompt_trace(target_case),
            timeout=120,
        )
    except asyncio.TimeoutError:
        return {
            "status": "success",
            "verdict": "error",
            "reasoning": "Agent re-prompt timed out after 120s",
            "confidence": 0.0,
            "details": {},
        }

    # Judge
    judge = Judge()
    eval_result = judge.score(replay_result)

    return {
        "status": "success",
        **eval_result,
        "original_response": replay_result.get("original_response"),
        "new_response": replay_result.get("new_response"),
        "flag_comment": replay_result.get("flag_comment"),
        "duration_ms": replay_result.get("duration_ms"),
    }


@router.post("/traces/eval-lightweight-all")
async def eval_lightweight_all(request: ReplayAllRequest):
    """Evaluate all pending eval cases."""
    import asyncio
    from tests.tracing.eval_store import eval_case_manager
    from tests.agentic.evals.replay_runner import re_prompt_trace
    from tests.agentic.evals.judge import Judge

    cases = eval_case_manager.get_eval_cases(
        status="pending",
        agent_type=request.agent_type,
        limit=request.limit,
    )
    judge = Judge()

    results = []
    summary = {"fixed": 0, "still_broken": 0, "regressed": 0, "errors": 0}

    for case in cases:
        try:
            replay_result = await asyncio.wait_for(
                re_prompt_trace(case),
                timeout=120,
            )
            eval_result = judge.score(replay_result)

            verdict = eval_result.get("verdict", "error")
            if verdict in summary:
                summary[verdict] += 1
            else:
                summary["errors"] += 1

            results.append({
                "case_id": str(case.get("_id", "")),
                "session_id": case.get("session_id"),
                "turn_index": case.get("turn_index"),
                **eval_result,
                "original_response": replay_result.get("original_response"),
                "new_response": replay_result.get("new_response"),
                "flag_comment": replay_result.get("flag_comment"),
                "duration_ms": replay_result.get("duration_ms"),
            })
        except asyncio.TimeoutError:
            summary["errors"] += 1
            results.append({
                "case_id": str(case.get("_id", "")),
                "session_id": case.get("session_id"),
                "turn_index": case.get("turn_index"),
                "verdict": "error",
                "error": "Agent re-prompt timed out after 120s",
            })
        except Exception as e:
            summary["errors"] += 1
            results.append({
                "case_id": str(case.get("_id", "")),
                "session_id": case.get("session_id"),
                "turn_index": case.get("turn_index"),
                "verdict": "error",
                "error": str(e),
            })

    # Record the eval run
    run_id = eval_case_manager.record_eval_run(results, summary)

    return {
        "run_id": run_id,
        "summary": summary,
        "results": results,
    }


# ──────────────────────────────────────────────
# Eval Runs
# ──────────────────────────────────────────────

@router.get("/eval-runs")
async def get_eval_runs(limit: int = 20):
    """List recent eval runs (without full results)."""
    from tests.tracing.eval_store import eval_case_manager
    runs = eval_case_manager.get_eval_runs(limit=limit)
    return {"runs": _serialise_docs(runs), "count": len(runs)}


@router.get("/eval-runs/{run_id}")
async def get_eval_run(run_id: str):
    """Get a single eval run with full results."""
    from tests.tracing.eval_store import eval_case_manager
    run = eval_case_manager.get_eval_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Eval run not found")
    if "_id" in run:
        run["_id"] = str(run["_id"])
    return run


# ──────────────────────────────────────────────
# Export
# ──────────────────────────────────────────────

@router.post("/traces/export-scenario")
async def export_scenario(request: ExportScenarioRequest):
    """Export a trace as a YAML test scenario."""
    import yaml
    from tests.tracing.tracer import turn_tracer

    turns = turn_tracer.get_session_turns(request.session_id)
    target_turn = None
    for turn in turns:
        if turn.get("turn_index") == request.turn_index:
            target_turn = turn
            break

    if not target_turn:
        raise HTTPException(status_code=404, detail="Turn not found")

    scenario_name = request.scenario_name or f"scenario_{request.session_id[:8]}_turn{request.turn_index}"

    input_data = target_turn.get("input", {})
    message_history = input_data.get("message_history", [])
    current_msg = input_data.get("message", "")

    if message_history:
        setup_messages = message_history
    else:
        setup_messages = [{"role": "user", "content": current_msg}] if current_msg else []

    scenario = {
        "name": scenario_name,
        "description": "Captured from live session",
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
            "comment": "TODO: define expected behavior",
        },
    }

    yaml_str = yaml.dump(scenario, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return {
        "scenario_name": scenario_name,
        "yaml": yaml_str,
        "save_to": f"tests/tracing/scenarios/captured/{scenario_name}.yaml",
    }


# ──────────────────────────────────────────────
# Seed & Reset Endpoints
# ──────────────────────────────────────────────

@router.post("/seed-user")
async def seed_user(request: SeedUserRequest):
    """Create or update a test user with a pre-built plan."""
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
    """Reset plan, progress, and chat data for a user."""
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

    db["users"].update_one(
        {"_id": obj_id},
        {"$unset": unset_fields},
    )

    db["chatsessions"].delete_many({"userId": obj_id})

    return {
        "status": "reset",
        "user_id": request.user_id,
        "kept_profile": request.keep_profile,
    }
