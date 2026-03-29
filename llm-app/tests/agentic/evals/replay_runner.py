"""Replay Runner — deterministically replays flagged traces from MongoDB.

Pulls flagged traces, mocks tool calls with recorded results, replays the
agent with identical inputs, and returns both original + new response for
the judge to compare.

Usage:
    from tests.agentic.evals.replay_runner import load_flagged_traces, replay_trace

    traces = load_flagged_traces()
    for trace in traces:
        result = await replay_trace(trace)
        # result has {original, new_response, flag_comment, meta}
"""

import asyncio
import logging
import os
import sys
import time
from typing import Any

logger = logging.getLogger(__name__)

# Ensure llm-app root is on the path
_LLM_APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _LLM_APP_ROOT not in sys.path:
    sys.path.insert(0, _LLM_APP_ROOT)


# ═══════════════════════════════════════════════════════════════════
# Trace Loading
# ═══════════════════════════════════════════════════════════════════

def load_flagged_traces(
    agent_type: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """Load flagged traces from MongoDB.

    Args:
        agent_type: Filter by agent type ("dsa", "ds", "onboarding", etc.)
        limit: Max traces to load.

    Returns:
        List of flagged trace dicts from MongoDB.
    """
    try:
        from tests.tracing.tracer import turn_tracer
        collection = turn_tracer._get_collection()
        if collection is None:
            logger.error("Could not connect to MongoDB for traces")
            return []

        query: dict[str, Any] = {"flagged": True}
        if agent_type:
            query["agent_type"] = agent_type

        traces = list(
            collection.find(query)
            .sort("timestamp", -1)
            .limit(limit)
        )
        logger.info(f"Loaded {len(traces)} flagged traces")
        return traces

    except Exception as e:
        logger.error(f"Failed to load flagged traces: {e}")
        return []


def load_traces_from_json(json_dir: str) -> list[dict]:
    """Load traces from exported JSON files (offline mode)."""
    import json
    from pathlib import Path

    traces = []
    directory = Path(json_dir)
    if not directory.exists():
        logger.warning(f"JSON trace directory not found: {json_dir}")
        return []

    for json_file in sorted(directory.glob("*.json")):
        try:
            with open(json_file) as f:
                trace = json.load(f)
            if trace.get("flagged"):
                traces.append(trace)
        except Exception as e:
            logger.warning(f"Skipping {json_file}: {e}")

    logger.info(f"Loaded {len(traces)} flagged traces from JSON")
    return traces


# ═══════════════════════════════════════════════════════════════════
# Tool Mocking
# ═══════════════════════════════════════════════════════════════════

def _build_mock_tools(tool_events: list[dict]) -> dict[str, Any]:
    """Build a lookup of tool name → recorded output for mocking.

    Args:
        tool_events: List of {tool, input, output, ...} from the trace.

    Returns:
        Dict mapping tool_name → list of recorded outputs (in order).
    """
    mock_results: dict[str, list] = {}
    for event in tool_events:
        tool_name = event.get("tool", "")
        output = event.get("output_preview", event.get("output", ""))
        if tool_name:
            mock_results.setdefault(tool_name, []).append(output)
    return mock_results


def _create_mock_tool(name: str, recorded_outputs: list[str]):
    """Create a mock tool that returns recorded outputs in order."""
    from langchain_core.tools import tool as tool_decorator

    call_index = {"i": 0}

    @tool_decorator
    def mock_tool(**kwargs) -> str:
        """Mock tool that returns recorded output."""
        idx = call_index["i"]
        call_index["i"] += 1
        if idx < len(recorded_outputs):
            return recorded_outputs[idx]
        return f"[MOCK] No recorded output for call #{idx + 1} to {name}"

    mock_tool.name = name
    mock_tool.__name__ = name
    return mock_tool




# ═══════════════════════════════════════════════════════════════════
# Lightweight Re-prompt Eval (Phase 3)
# ═══════════════════════════════════════════════════════════════════

async def re_prompt_trace(trace: dict) -> dict[str, Any]:
    """Lightweight evaluate a flagged trace by re-prompting the live agent.

    Unlike `replay_trace`, this does NOT mock tools. It spins up the real
    agent with real tools, seeds the store and memory exactly as they were,
    and simply re-sends the input to see if current prompts/logic fix the flag.

    This is much more robust to prompt changes that alter tool sequences.
    """
    from langgraph.store.memory import InMemoryStore
    from langgraph.checkpoint.memory import MemorySaver
    from langchain_core.messages import HumanMessage, AIMessage

    input_data = trace.get("input", {})
    output_data = trace.get("output", {})
    meta = {
        "session_id": trace.get("session_id", ""),
        "turn_index": trace.get("turn_index", 0),
        "module": trace.get("module", "dsa"),
        "agent_type": trace.get("agent_type", trace.get("module", "dsa")),
        "mode": input_data.get("mode", "learn"),
        "user_id": trace.get("user_id", ""),
    }

    original_message = input_data.get("message", "")
    original_response = output_data.get("response", "")
    flag_comment = trace.get("flag_comment", "")
    tutor_context = input_data.get("tutor_context") or {}
    store_before = input_data.get("store_before") or input_data.get("store_snapshot") or {}
    message_history = input_data.get("message_history", [])

    if not original_message or not flag_comment:
        return _error_result(meta, "No input message or flag comment in trace")

    if meta["agent_type"] == "plan_generator":
        return await _replay_plan_generation(trace, meta, original_response, flag_comment, input_data, output_data)

    # 1. Seed store and memory
    store = InMemoryStore()
    user_id = meta["user_id"] or f"eval_{meta['session_id']}"

    from app.tutor.core.workspace import initialize_tutor_workspace
    await initialize_tutor_workspace(store, user_id)

    for fname, content in store_before.items():
        await store.aput(
            (user_id,),
            fname,
            {"content": content.split("\n") if isinstance(content, str) else content},
        )

    checkpointer = MemorySaver()
    thread_id = f"reprompt_{meta['session_id']}_{meta['turn_index']}"

    lc_messages = []
    for msg in message_history:
        role = msg.get("role", msg.get("type", ""))
        content = msg.get("content", "")
        if role in ("user", "human"):
            lc_messages.append(HumanMessage(content=content))
        elif role in ("assistant", "ai"):
            lc_messages.append(AIMessage(content=content))

    # 2. Create REAL agent (no mock tools)
    from app.tutor.core.config import get_tutor_model
    model = get_tutor_model()
    
    if meta["agent_type"] == "ds":
        from app.tutor.ds.agent import create_ds_agent
        agent = create_ds_agent(model=model, store=store, checkpointer=checkpointer)
    elif meta["agent_type"] == "onboarding":
        from app.onboarding.agent import get_onboarding_agent
        agent = get_onboarding_agent()
    else:
        from app.tutor.dsa.agent import create_dsa_agent
        agent = create_dsa_agent(model=model, store=store, checkpointer=checkpointer)

    mode = meta["mode"]
    active_mode = mode.upper() if mode else "LEARN"
    tagged_message = f"[{active_mode}] {original_message}"

    config = {
        "configurable": {
            "thread_id": thread_id,
            "assistant_id": user_id,
            "module": meta["module"],
        },
        "recursion_limit": 50,
    }

    all_messages = lc_messages + [HumanMessage(content=tagged_message)]
    inputs = {
        "messages": all_messages,
        "tutor_context": tutor_context,
    }

    # 3. Invoke agent
    start = time.time()
    try:
        result = await agent.ainvoke(inputs, config=config)
    except Exception as e:
        return _error_result(meta, f"Agent reprompt failed: {e}")
    elapsed_ms = int((time.time() - start) * 1000)

    # Extract new response
    agent_messages = result.get("messages", [])
    new_response = ""
    new_tools_called = []
    if agent_messages:
        last_msg = agent_messages[-1]
        content = last_msg.content
        if isinstance(content, list):
            text_blocks = [
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            new_response = "\n".join(text_blocks) or str(content)
        else:
            new_response = str(content)

        # Collect tools actually called
        for m in agent_messages:
            if hasattr(m, "tool_calls") and m.tool_calls:
                for tc in m.tool_calls:
                    new_tools_called.append(tc.get("name", ""))

    return {
        "meta": meta,
        "original_response": original_response,
        "new_response": new_response,
        "flag_comment": flag_comment,
        "original_tools": output_data.get("tools_called", []),
        "new_tools": list(set(new_tools_called)),
        "duration_ms": elapsed_ms,
        "trace_id": str(trace.get("_id", "")),
    }


# ═══════════════════════════════════════════════════════════════════
# Plan Re-Generation (for plan_generator traces)
# ═══════════════════════════════════════════════════════════════════

async def _replay_plan_generation(
    trace: dict,
    meta: dict,
    original_response: str,
    flag_comment: str,
    input_data: dict,
    output_data: dict,
) -> dict[str, Any]:
    """Re-run plan generation with the current model and return for judge comparison.

    Extracts student profile from the trace's store_before, calls
    PlanningService.generate_initial_plan(), and returns the new plan
    summary alongside the original for the judge to compare.
    """
    store_before = input_data.get("store_before") or {}
    profile_raw = store_before.get("profile")

    if not profile_raw:
        return _error_result(
            meta,
            "No student profile in trace store_before — cannot re-generate plan. "
            "This trace may have been created before plan tracing was added."
        )

    start = time.time()
    try:
        import ast
        from app.models.plan_models import StudentProfile
        from app.planning.service import PlanningService

        # Parse profile — it might be a string repr of a dict or an actual dict
        if isinstance(profile_raw, str):
            profile_dict = ast.literal_eval(profile_raw)
        else:
            profile_dict = profile_raw

        # Reconstruct the student profile
        student_profile = StudentProfile(**profile_dict)

        # Get the same parameters used in original generation
        available_weeks_raw = store_before.get("available_weeks", "12")
        available_weeks = int(available_weeks_raw) if isinstance(available_weeks_raw, str) else available_weeks_raw
        feedback_raw = store_before.get("feedback", "")
        feedback = feedback_raw if feedback_raw and feedback_raw != "None" else None
        module = meta.get("module", "dsa")

        # Re-run plan generation with the CURRENT model
        service = PlanningService()
        new_plan, new_progress = await service.generate_initial_plan(
            student_profile=student_profile,
            course_id=module,
            feedback=feedback,
        )

        # Build a summary of the new plan for the judge
        week_summaries = []
        for week in new_plan.weeks:
            topic_titles = [t.title for t in week.topics[:5]]
            more = len(week.topics) - 5
            summary = f"Week {week.week_number} ({week.focus_area}): {', '.join(topic_titles)}"
            if more > 0:
                summary += f" +{more} more"
            week_summaries.append(summary)

        new_response = (
            f"Generated {new_plan.total_topics}-topic, {new_plan.total_weeks}-week plan.\n"
            f"Student goal: {student_profile.goal}\n"
            f"Weekly hours: {student_profile.weekly_hours}h/week\n"
            f"Timeline: {available_weeks} weeks\n\n"
            f"Plan breakdown:\n" + "\n".join(week_summaries)
        )

    except Exception as e:
        return _error_result(meta, f"Plan re-generation failed: {e}")

    elapsed_ms = int((time.time() - start) * 1000)

    return {
        "meta": meta,
        "original_response": original_response,
        "new_response": new_response,
        "flag_comment": flag_comment,
        "original_tools": output_data.get("tools_called", []),
        "new_tools": ["generate_topic_ordering", "build_weekly_plan"],
        "duration_ms": elapsed_ms,
        "trace_id": str(trace.get("_id", "")),
    }


# ═══════════════════════════════════════════════════════════════════
# Agent Creation with Mocked Tools
# ═══════════════════════════════════════════════════════════════════

def _create_agent_with_mock_tools(
    agent_type: str,
    store,
    checkpointer,
    tool_events: list[dict],
):
    """Create agent with real LLM but mocked tools (deterministic replay)."""

    # Build mock tools from recorded tool events
    mock_tool_map = _build_mock_tools(tool_events)
    mock_tools = [
        _create_mock_tool(name, outputs)
        for name, outputs in mock_tool_map.items()
    ]

    # Get model
    from app.tutor.core.config import get_tutor_model
    model = get_tutor_model()

    # Create agent based on type
    if agent_type == "ds":
        from app.tutor.ds.agent import create_ds_agent
        return create_ds_agent(
            model=model, store=store, checkpointer=checkpointer,
            override_tools=mock_tools,
        )
    elif agent_type == "onboarding":
        from app.onboarding.agent import get_onboarding_agent
        # Onboarding agent may not support override_tools yet
        return get_onboarding_agent()
    else:
        # Default: DSA
        from app.tutor.dsa.agent import create_dsa_agent
        return create_dsa_agent(
            model=model, store=store, checkpointer=checkpointer,
            override_tools=mock_tools,
        )


def _error_result(meta: dict, error: str) -> dict:
    """Return an error result dict."""
    return {
        "meta": meta,
        "original_response": "",
        "new_response": f"[ERROR] {error}",
        "flag_comment": "",
        "original_tools": [],
        "new_tools": [],
        "duration_ms": 0,
        "trace_id": "",
    }
