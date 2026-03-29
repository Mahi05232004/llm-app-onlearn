"""
Orchestrator API Endpoint.

Handles all tutor chat interactions via streaming (SSE) and non-streaming.

Architecture (v2):
  - thread_id = {module}_{sessionId} — one thread PER QUESTION SESSION
  - Dynamic context via TutorContextMiddleware (interface + question data)
  - No session recap injection — per-session threading eliminates the need
  - Learning plan accessed via tools (no sync_global_plan)
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, AsyncGenerator
import logging
import json
import asyncio

from app.tutor import get_tutor_agent
from app.tutor.core.workspace import initialize_tutor_workspace
from app.onboarding.agent import get_onboarding_agent
from core.course_data import get_question_by_id

from app.api.helpers.sse_streaming import stream_agent_events, parse_agent_response

router = APIRouter()
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Request / Response Models
# ═══════════════════════════════════════════════════════════════════════════════

class OrchestratorRequest(BaseModel):
    """Request model for orchestrator chat."""
    message: str
    sessionId: str = ""
    mode: str = "learn"  # 'learn' or 'code' — which UI the student is using
    module: str = "dsa"  # active learning module ('dsa', 'ds', etc.)
    threadId: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    is_onboarding: bool = False
    user_id: Optional[str] = None
    messages: Optional[list] = None
    files: Optional[Dict[str, Any]] = None


class OrchestratorResponse(BaseModel):
    """Response model for orchestrator chat."""
    response: str
    threadId: str
    activeAgent: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# Shared Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _serialise_messages(messages) -> list[dict[str, str]]:
    """Convert langchain BaseMessage list to simple role/content dicts for tracing."""
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
    result = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        elif isinstance(msg, SystemMessage):
            role = "system"
        elif isinstance(msg, ToolMessage):
            role = "tool"
        else:
            role = "unknown"
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        entry = {"role": role, "content": content[:2000]}  # cap per-message size
        if isinstance(msg, ToolMessage):
            entry["tool_call_id"] = getattr(msg, "tool_call_id", "")
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            entry["tool_calls"] = [
                {"name": tc.get("name", ""), "args": tc.get("args", {})}
                for tc in msg.tool_calls
            ]
        result.append(entry)
    return result


def _extract_topic_id(files: Dict[str, Any] | None) -> str | None:
    """Extract topicId from /topic.json in request files."""
    if not files:
        return None
    topic_file = files.get("/topic.json")
    if not topic_file:
        return None
    try:
        content = topic_file.get("content", "")
        if isinstance(content, str):
            data = json.loads(content)
        elif isinstance(content, dict):
            data = content
        else:
            return None
        return data.get("topic_id")
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None


async def _fetch_session_info(session_id: str) -> tuple[str | None, Any]:
    """Fetch userId and last_interaction_at from MongoDB session doc.

    Returns (user_id, last_interaction_at) — either may be None.
    """
    user_id = None
    last_interaction_at = None
    try:
        from bson import ObjectId
        from core.mongo_db import mongo_db_manager
        db = mongo_db_manager.get_database()
        if session_id:
            session_doc = await asyncio.to_thread(
                db["chatsessions"].find_one,
                {"_id": ObjectId(session_id)},
                {"last_updated": 1, "userId": 1},
            )
            if session_doc:
                if session_doc.get("userId"):
                    user_id = str(session_doc["userId"])
                if session_doc.get("last_updated"):
                    last_updated = session_doc["last_updated"]
                    if isinstance(last_updated, str):
                        from datetime import datetime
                        last_interaction_at = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                    else:
                        last_interaction_at = last_updated
    except Exception as e:
        logger.debug(f"Could not fetch session info: {e}")
    return user_id, last_interaction_at


def _build_thread_id(module: str, session_id: str) -> str:
    """Build per-session thread ID: {module}_{sessionId}."""
    return f"{module}_{session_id}"


async def _fetch_learning_plan(user_id: str, module: str) -> tuple[dict | None, bool]:
    """Fetch the student's learning plan for the active module.

    Returns (plan_dict, user_found):
    - (plan, True)  → plan exists in DB
    - (None, True)  → user exists but no plan → caller should generate default
    - (None, False) → DB error or invalid ID → caller should NOT generate default
    """
    if not user_id:
        return None, False
    try:
        from bson import ObjectId
        if not ObjectId.is_valid(user_id):
            return None, False

        from core.mongo_db import mongo_db_manager
        db = mongo_db_manager.get_database()

        # Fetch both new module structure and legacy flat fields
        user_doc = await asyncio.to_thread(
            db["users"].find_one,
            {"_id": ObjectId(user_id)},
            {
                f"modules.{module}.learningPlan": 1,
                "learningPlan": 1,
                "learningPlanDS": 1,
            },
        )
        if not user_doc:
            return None, False  # user doesn't exist — don't create default

        # 1. Try new nested structure
        modules = user_doc.get("modules") or {}
        module_data = modules.get(module) or {}
        plan = module_data.get("learningPlan")
        if plan:
            return plan, True

        # 2. Try legacy flat fields
        legacy_plan = None
        if module == "dsa":
            legacy_plan = user_doc.get("learningPlan")
        elif module == "ds":
            legacy_plan = user_doc.get("learningPlanDS") or user_doc.get("learningPlan")

        if legacy_plan:
            return legacy_plan, True

        # User exists but has no plan at all
        return None, True

    except Exception as e:
        logger.debug(f"Could not fetch learning plan: {e}")
        return None, False


async def _ensure_learning_plan(user_id: str, module: str) -> dict | None:
    """Fetch or create a default learning plan for the user.

    Safe: only creates a default plan when the user exists but has no plan.
    Never overwrites an existing plan. Returns None on DB errors.
    """
    plan, user_found = await _fetch_learning_plan(user_id, module)

    if plan:
        return plan

    if not user_found:
        # DB error or invalid user — don't generate default
        return None

    # User exists but has no plan → generate default and save
    try:
        from app.api.endpoints.plan import build_default_plan
        from app.planning.plan_store import plan_store

        default_plan = build_default_plan(module)
        if not default_plan:
            return None

        progress = {
            "total_topics": default_plan.get("total_topics", 0),
            "completed_topics": 0,
            "completion_percentage": 0.0,
            "days_remaining": default_plan.get("total_weeks", 0) * 7,
            "pace_status": "on_track",
            "pace_message": "Just getting started!",
        }

        plan_store.save_plan_data(
            user_id=user_id,
            module=module,
            plan=default_plan,
            progress=progress,
            status="done",
        )
        logger.info(f"[Orchestrator] Created default plan for user={user_id}, module={module}")
        return default_plan

    except Exception as e:
        logger.warning(f"[Orchestrator] Failed to create default plan: {e}")
        return None


def _build_config(thread_id: str, user_id: str, module: str, tutor_context: dict | None = None) -> dict:
    """Build agent invocation config with all required configurable keys."""
    cfg: dict = {
        "configurable": {
            "thread_id": thread_id,
            "assistant_id": user_id,   # Used by InjectedToolArg and StoreBackend namespace
            "module": module,          # Used by learning plan tools
        },
        "recursion_limit": 100,
    }
    if tutor_context is not None:
        # PrivateStateAttr has input=True (OmitFromSchema), so tutor_context cannot be
        # passed via the inputs dict — LangGraph strips it. Pass via configurable instead
        # and read via get_config() in TutorContextMiddleware.
        cfg["configurable"]["tutor_context"] = tutor_context
    return cfg


def _build_tutor_context(
    mode: str,
    module: str,
    question_data: dict | None,
    code_context: dict | None,
    last_interaction_at: Any = None,
    session_id: str | None = None,
    learning_plan: dict | None = None,
) -> dict:
    """Build the tutor_context dict for TutorContextMiddleware."""
    return {
        "mode": mode,
        "module": module,
        "question_data": question_data,
        "code_context": code_context,
        "last_interaction_at": last_interaction_at,
        "session_id": session_id,
        "learning_plan": learning_plan,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Non-Streaming Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/", response_model=OrchestratorResponse)
async def chat_with_orchestrator(request: OrchestratorRequest):
    """Non-streaming chat with the tutor agent. Use /stream for SSE."""
    try:
        user_id = request.user_id
        module = request.module

        topic_id = _extract_topic_id(request.files)
        question_data = await asyncio.to_thread(get_question_by_id, topic_id, course_id=module) if topic_id else None

        # Fetch session info (userId, last_interaction_at)
        db_user_id, last_interaction_at = await _fetch_session_info(request.sessionId)
        if not user_id and db_user_id:
            user_id = db_user_id
        user_id = user_id or request.sessionId

        # Per-session thread
        thread_id = _build_thread_id(module, request.sessionId)

        # Ensure workspace exists
        from app.tutor.core.store import get_tutor_store
        store = get_tutor_store()
        await initialize_tutor_workspace(store, user_id)

        # Fetch learning plan
        learning_plan = await _ensure_learning_plan(user_id, module)

        tutor_context = _build_tutor_context(
            mode=request.mode,
            module=module,
            question_data=question_data,
            code_context=request.context,
            last_interaction_at=last_interaction_at,
            session_id=request.sessionId,
            learning_plan=learning_plan,
        )

        active_mode = request.mode.upper() if request.mode else "LEARN"
        tagged_message = f"[{active_mode}] {request.message}"

        config = _build_config(thread_id, user_id, module, tutor_context=tutor_context)

        inputs = {
            "messages": [("user", tagged_message)],
        }

        try:
            result = await get_tutor_agent(module=module).ainvoke(inputs, config=config)
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "503" in err_str or "UNAVAILABLE" in err_str:
                logger.warning(f"[Orchestrator] Primary model failed (429/503), falling back")
                from app.tutor import get_fallback_tutor_agent
                try:
                    result = await get_fallback_tutor_agent(module=module).ainvoke(inputs, config=config)
                except Exception as fallback_err:
                    logger.error(f"[Orchestrator] Both models failed: {fallback_err}", exc_info=True)
                    return OrchestratorResponse(
                        response="Something went wrong on our end. Please tap retry to try again.",
                        threadId=thread_id,
                    )
            else:
                raise

        # --- Extract response text ---
        def _extract_text(result: dict) -> str:
            messages = result.get("messages", [])
            if not messages:
                return ""
            last_message = messages[-1]
            content = last_message.content
            if isinstance(content, list):
                text_blocks = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                return "\n".join(text_blocks).strip()
            return str(content).strip()

        final_response = _extract_text(result)

        # --- Empty/corrupted response detection: retry with fallback ---
        if not final_response:
            logger.warning("[Orchestrator] Primary model returned empty response, trying fallback")
            from app.tutor import get_fallback_tutor_agent
            try:
                result = await get_fallback_tutor_agent(module=module).ainvoke(inputs, config=config)
                final_response = _extract_text(result)
            except Exception as fallback_err:
                logger.error(f"[Orchestrator] Fallback also failed: {fallback_err}", exc_info=True)

        if not final_response:
            final_response = "Something went wrong on our end. Please tap retry to try again."

        return OrchestratorResponse(
            response=final_response,
            threadId=thread_id,
            activeAgent="tutor",
        )

    except Exception as e:
        logger.error(f"Error in orchestrator chat: {str(e)}", exc_info=True)
        return OrchestratorResponse(
            response="Something went wrong on our end. Please tap retry to try again.",
            threadId=thread_id if 'thread_id' in dir() else "",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Streaming Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/stream")
async def chat_with_orchestrator_stream(request: OrchestratorRequest):
    """Streaming chat — returns Server-Sent Events with token chunks.

    Event types: token, thinking, tool_start, tool_end, done, error,
    onboarding_complete.
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            user_id = request.user_id or request.sessionId
            module = request.module

            # ── Onboarding path ──
            if request.is_onboarding:
                agent_to_stream = get_onboarding_agent(module_id=module)
                session_id = request.sessionId
                thread_id = f"onboarding_{module}_{session_id}"
                logger.info(f"[Orchestrator Stream] Onboarding for session: {session_id}")

                message_text = request.message
                if request.message == '[START_ONBOARDING]':
                    message_text = "Hi, I'm new here and want to start learning!"

                inputs = {
                    "messages": [("user", message_text)],
                    "user_id": request.sessionId,
                }
                config = {
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": 100,
                }

                acc = {"full_response": ""}
                try:
                    async for sse in stream_agent_events(agent_to_stream, inputs, config, accumulator=acc):
                        yield sse

                    # Check for onboarding completion in tool events
                    for te in acc.get("tool_events", []):
                        output = te.get("output_preview", "")
                        if "onboarding_complete" in output:
                            try:
                                tool_data = json.loads(output)
                                if tool_data.get("status") == "onboarding_complete":
                                    yield f"data: {json.dumps({'type': 'onboarding_complete', 'student_profile': tool_data.get('student_profile')})}\n\n"
                                    return
                            except (json.JSONDecodeError, TypeError):
                                pass
                except asyncio.CancelledError:
                    logger.info(f"Onboarding stream cancelled for user {request.sessionId}")
                    return

                # Record onboarding trace
                trace_id = None
                try:
                    from tests.tracing.tracer import turn_tracer
                    onboarding_tools = list({ev["tool"] for ev in acc.get("tool_events", []) if ev.get("tool")})
                    trace_id = turn_tracer.record_turn(
                        session_id=session_id,
                        user_id=user_id,
                        input_message=request.message,
                        input_files={},
                        output_response=acc["full_response"],
                        output_files={},
                        agent_name="onboarding",
                        agent_type="onboarding",
                        tools_called=onboarding_tools,
                        tool_events=acc.get("tool_events", []),
                        thread_id=thread_id,
                        mode="onboarding",
                        module=module,
                    )
                except Exception:
                    pass  # non-critical

                yield f"data: {json.dumps({'type': 'done', 'threadId': thread_id, 'traceId': trace_id, 'actions': ['next_question'], 'suggestions': [], 'nextQuestionId': None})}\n\n"
                return

            # ── Main tutor agent path ──
            tutor_agent = get_tutor_agent(module=module)

            topic_id = _extract_topic_id(request.files)
            question_data = await asyncio.to_thread(get_question_by_id, topic_id, course_id=module) if topic_id else None

            # Fetch session info
            db_user_id, last_interaction_at = await _fetch_session_info(request.sessionId)
            if not user_id and db_user_id:
                user_id = db_user_id
            user_id = user_id or request.sessionId

            # Per-session thread
            thread_id = _build_thread_id(module, request.sessionId)

            logger.info(f"[Tutor Stream] user={user_id}, mode={request.mode}, thread={thread_id}")
            if question_data:
                logger.info(
                    f"[Context] topic_id={topic_id}, "
                    f"question_title={question_data.get('question_title', 'NONE')}, "
                    f"concepts={question_data.get('concepts') or question_data.get('standard_concepts', 'NONE')}"
                )

            # Ensure workspace exists
            from app.tutor.core.store import get_tutor_store
            store = get_tutor_store()
            await initialize_tutor_workspace(store, user_id)

            # Fetch learning plan
            learning_plan = await _ensure_learning_plan(user_id, module)

            # Build context
            tutor_context = _build_tutor_context(
                mode=request.mode,
                module=module,
                question_data=question_data,
                code_context=request.context,
                last_interaction_at=last_interaction_at,
                session_id=request.sessionId,
                learning_plan=learning_plan,
            )

            # Prepend mode tag to message
            active_mode = request.mode.upper() if request.mode else "LEARN"
            tagged_message = f"[{active_mode}] {request.message}"

            config = _build_config(thread_id, user_id, module, tutor_context=tutor_context)

            inputs = {
                "messages": [("user", tagged_message)],
            }

            acc = {"full_response": "", "tool_events": [], "output_files": {}, "scratchpad_updated": False}

            # Capture store state BEFORE the turn (for eval replicability)
            store_before = {}
            try:
                import os as _os
                if _os.environ.get("ENABLE_TEST_ENDPOINTS", "0") == "1":
                    for fname in ("short_term_plan.md", "AGENTS.md"):
                        item = await store.aget((user_id,), fname)
                        if item and item.value:
                            content = item.value.get("content", [])
                            store_before[fname] = "\n".join(content) if isinstance(content, list) else str(content)
            except Exception:
                pass  # non-critical

            try:
                async for sse in stream_agent_events(tutor_agent, inputs, config, accumulator=acc):
                    yield sse
            except asyncio.CancelledError:
                logger.info(f"Tutor stream cancelled for user {user_id}")
                return
            except Exception as primary_err:
                err_str = str(primary_err)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "503" in err_str or "UNAVAILABLE" in err_str:
                    logger.warning(f"[Orchestrator] Primary model failed (429/503), falling back")
                    try:
                        from app.tutor import get_fallback_tutor_agent
                        fallback_agent = get_fallback_tutor_agent(module=module)
                        acc = {"full_response": "", "tool_events": [], "output_files": {}, "scratchpad_updated": False}
                        async for sse in stream_agent_events(fallback_agent, inputs, config, accumulator=acc):
                            yield sse
                    except Exception as fallback_err:
                        yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong on our end. Please tap retry to try again.', 'canRetry': True})}\n\n"
                        raise ValueError("Both primary and fallback models failed")
                else:
                    raise

            # --- Empty/corrupted response detection: retry with fallback ---
            if not acc["full_response"].strip():
                logger.warning("[Orchestrator] Primary model returned empty response, trying fallback")
                try:
                    from app.tutor import get_fallback_tutor_agent
                    fallback_agent = get_fallback_tutor_agent(module=module)
                    acc = {"full_response": "", "tool_events": [], "output_files": {}, "scratchpad_updated": False}
                    async for sse in stream_agent_events(fallback_agent, inputs, config, accumulator=acc):
                        yield sse
                except Exception as fallback_err:
                    logger.error(f"[Orchestrator] Fallback also returned empty/failed: {fallback_err}", exc_info=True)

                # If still empty after fallback, emit error and raise exception so status is marked as error
                if not acc["full_response"].strip():
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong on our end. Please tap retry to try again.', 'canRetry': True})}\n\n"
                    raise ValueError("Empty response received from all models")

            # Parse response metadata (must happen before trace + done event)
            parsed = parse_agent_response(acc["full_response"])

            # ── Record turn trace ──
            trace_id = None
            try:
                from tests.tracing.tracer import turn_tracer

                tools_called = list({ev["tool"] for ev in acc["tool_events"] if ev.get("tool")})

                message_history = []
                try:
                    state_snapshot = await tutor_agent.aget_state(config)
                    all_messages = state_snapshot.values.get("messages", [])
                    if all_messages:
                        message_history = _serialise_messages(all_messages)
                except Exception as hist_err:
                    logger.debug(f"Could not capture message history: {hist_err}")

                # Capture store snapshot (memory files after response)
                store_after = {}
                try:
                    for fname in ("short_term_plan.md", "AGENTS.md"):
                        item = await store.aget((user_id,), fname)
                        if item and item.value:
                            content = item.value.get("content", [])
                            store_after[fname] = "\n".join(content) if isinstance(content, list) else str(content)
                except Exception as store_err:
                    logger.debug(f"Could not capture store after: {store_err}")

                trace_id = turn_tracer.record_turn(
                    session_id=request.sessionId,
                    user_id=user_id,
                    input_message=request.message,
                    input_files=tutor_context,
                    output_response=acc["full_response"],
                    output_files=acc["output_files"],
                    agent_name="tutor",
                    agent_type=module,  # "dsa" or "ds"
                    tools_called=tools_called,
                    tool_events=acc["tool_events"],
                    message_history=message_history,
                    iteration=0,
                    thread_id=thread_id,
                    mode=request.mode,
                    module=module,
                    tutor_context=tutor_context,
                    store_before=store_before,
                    store_after=store_after,
                    suggestions=parsed["suggestions"],
                    actions=parsed["actions"],
                    scratchpad_updated=acc["scratchpad_updated"],
                )
            except Exception as trace_err:
                logger.debug(f"Turn tracing failed (non-critical): {trace_err}")

            # Parse response metadata
            yield f"data: {json.dumps({'type': 'done', 'threadId': thread_id, 'traceId': trace_id, 'activeAgent': 'tutor', 'suggestions': parsed['suggestions'], 'actions': parsed['actions'], 'nextQuestionId': parsed['next_question_id']})}\n\n"

            # ── Background reflection (fire-and-forget, every ~10 messages) ──
            try:
                state_snapshot = await tutor_agent.aget_state(config)
                msg_count = len(state_snapshot.values.get("messages", []))
                if msg_count > 0 and msg_count % 10 == 0:
                    from app.tutor.core.reflection import run_reflection
                    from app.tutor.core.config import get_tutor_model
                    # reflection uses ainvoke() — must NOT use a streaming model
                    # (streaming=True on an ainvoke causes Azure to return an empty SSE body)
                    reflection_model = get_tutor_model(model_type="flash", streaming=False)
                    asyncio.create_task(run_reflection(
                        store=store,
                        user_id=user_id,
                        module=module,
                        thread_id=thread_id,
                        agent=tutor_agent,
                        model=reflection_model,
                    ))
                    logger.info(f"[Reflection] Triggered at message {msg_count} for user={user_id}")
            except Exception as refl_err:
                logger.debug(f"Reflection trigger failed (non-critical): {refl_err}")

            logger.info(f"[Tutor Stream] Completed for user={user_id}")

        except Exception as e:
            logger.error(f"[Orchestrator Stream] Error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong on our end. Please tap retry to try again.', 'canRetry': True})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
