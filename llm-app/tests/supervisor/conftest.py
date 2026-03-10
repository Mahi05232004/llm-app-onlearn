"""
Shared test fixtures for the supervisor test suite.

Provides:
- Mock MongoDB (mongomock)
- Test data factories (users, plans, routing state)
- Mock agent factories (deterministic agents for graph loop testing)
- Graph state builders
"""
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, UTC
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


# ──────────────────────────────────────────────
# Test Data Constants
# ──────────────────────────────────────────────

SAMPLE_STUDENT_PROFILE = {
    "goal": "Get better at DSA for interviews",
    "experience": "intermediate",
    "weekly_hours": 10,
    "preferred_difficulty": "medium",
    "language": "Python",
}

SAMPLE_TOPIC = {
    "question_id": "two-sum",
    "title": "Two Sum",
    "difficulty": "easy",
    "estimated_minutes": 30,
    "category": "Arrays",
}

SAMPLE_TOPIC_2 = {
    "question_id": "binary-search",
    "title": "Binary Search",
    "difficulty": "easy",
    "estimated_minutes": 30,
    "category": "Binary Search",
}


# ──────────────────────────────────────────────
# Routing & Files Factories
# ──────────────────────────────────────────────

def make_routing(
    active_agent: str = "master",
    objective: str = "Help the student learn",
    expected_mode: str = "learn",
    question_id: str = "",
    handoff_summary: str = "",
    handoff_reason: str = "",
    pending_handoff: bool = False,
) -> dict:
    """Build a routing dict."""
    routing = {
        "active_agent": active_agent,
        "objective": objective,
        "expected_mode": expected_mode,
    }
    if question_id:
        routing["question_id"] = question_id
    if handoff_summary:
        routing["handoff_summary"] = handoff_summary
    if handoff_reason:
        routing["handoff_reason"] = handoff_reason
    if pending_handoff:
        routing["pending_handoff"] = True
    return routing


def make_routing_file(routing: dict) -> dict:
    """Wrap routing dict into a files entry."""
    return {
        "/routing.json": {
            "content": json.dumps(routing),
            "metadata": {"type": "routing"},
        }
    }


def make_files(
    routing: dict | None = None,
    plan: dict | None = None,
    progress: dict | None = None,
    topic_id: str = "",
    student_profile: dict | None = None,
    extra: dict | None = None,
) -> dict:
    """Build a virtual files dict for graph state."""
    files = {}
    if routing is not None:
        files.update(make_routing_file(routing))
    if plan is not None:
        files["/plan.json"] = {
            "content": json.dumps(plan),
            "metadata": {"type": "json", "source": "planning"},
        }
    if progress is not None:
        files["/progress.json"] = {
            "content": json.dumps(progress),
            "metadata": {"type": "json", "source": "planning"},
        }
    if topic_id:
        files["/topic.json"] = {
            "content": json.dumps({"topic_id": topic_id}),
            "metadata": {"type": "json", "source": "session"},
        }
    if student_profile is not None:
        files["/student_profile.json"] = {
            "content": json.dumps(student_profile),
            "metadata": {"type": "json", "source": "onboarding"},
        }
    if extra:
        files.update(extra)
    return files


def make_state(
    messages: list | None = None,
    files: dict | None = None,
    mode: str = "learn",
    user_id: str = "test_user_123",
    iteration: int = 0,
    **kwargs,
) -> dict:
    """Build an OrchestratorState dict."""
    return {
        "messages": messages or [HumanMessage(content="Hello")],
        "files": files or {},
        "mode": mode,
        "mode_changed": False,
        "user_id": user_id,
        "iteration": iteration,
        **kwargs,
    }


# ──────────────────────────────────────────────
# Mock Agent Factory
# ──────────────────────────────────────────────

def make_mock_agent(responses: list[dict]) -> MagicMock:
    """Create a mock agent that returns scripted responses.
    
    Each response dict should have:
      - messages: list of message objects to return
      - files: optional dict of files to return
    
    The mock will cycle through responses on successive calls.
    """
    call_idx = {"i": 0}
    
    async def mock_ainvoke(input_state, **kwargs):
        idx = call_idx["i"] % len(responses)
        call_idx["i"] += 1
        resp = responses[idx]
        return {
            "messages": resp.get("messages", [AIMessage(content="Mock response")]),
            "files": resp.get("files", input_state.get("files", {})),
        }
    
    agent = MagicMock()
    agent.ainvoke = AsyncMock(side_effect=mock_ainvoke)
    return agent


def make_handback_tool_message(
    reason: str = "objective_complete",
    summary: str = "Student completed the topic",
    tool_call_id: str = "test_tool_call_1",
) -> ToolMessage:
    """Create a ToolMessage that simulates hand_back_to_master."""
    routing = {
        "active_agent": "master",
        "objective": "",
        "expected_mode": "learn",
        "handoff_summary": summary,
        "handoff_reason": reason,
    }
    return ToolMessage(
        content=json.dumps({"action": "hand_back_to_master", "routing": routing}),
        tool_call_id=tool_call_id,
    )


def make_delegation_tool_message(
    agent_name: str = "concept_tutor",
    objective: str = "Teach Binary Search",
    expected_mode: str = "learn",
    question_id: str = "binary-search",
    tool_call_id: str = "test_tool_call_2",
) -> ToolMessage:
    """Create a ToolMessage that simulates delegate_to_agent."""
    routing = {
        "active_agent": agent_name,
        "objective": objective,
        "expected_mode": expected_mode,
        "question_id": question_id,
    }
    return ToolMessage(
        content=json.dumps({"action": "delegate_to_agent", "routing": routing}),
        tool_call_id=tool_call_id,
    )


# ──────────────────────────────────────────────
# Pytest Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def sample_routing():
    """Default routing state pointing to master."""
    return make_routing()


@pytest.fixture
def sample_files():
    """Default files dict with routing to master."""
    return make_files(routing=make_routing())


@pytest.fixture
def sample_state():
    """Default graph state with a user message and master routing."""
    return make_state(
        messages=[HumanMessage(content="Hello")],
        files=make_files(routing=make_routing()),
    )


# ──────────────────────────────────────────────
# Scenario State Builder
# ──────────────────────────────────────────────

def build_state_from_scenario(scenario: dict) -> dict:
    """Build an OrchestratorState from a YAML scenario dict.
    
    Reconstructs the full state including message history, files,
    routing, and mode — enabling scenario replay through node wrappers.
    """
    setup = scenario.get("setup", {})
    
    # Build messages from the scenario's message list
    messages = []
    for m in setup.get("messages", []):
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role in ("assistant", "ai"):
            # Reconstruct tool_calls if present
            tool_calls = m.get("tool_calls", [])
            if tool_calls:
                messages.append(AIMessage(
                    content=content,
                    tool_calls=[
                        {"name": tc.get("name", ""), "args": tc.get("args", {}),
                         "id": f"replay_{tc.get('name', '')}", "type": "tool_call"}
                        for tc in tool_calls
                    ],
                ))
            else:
                messages.append(AIMessage(content=content))
        elif role == "tool":
            messages.append(ToolMessage(
                content=content,
                tool_call_id=m.get("tool_call_id", "replay_tool"),
            ))
    
    if not messages:
        messages = [HumanMessage(content="Hello")]
    
    # Build files dict — merge explicit files with routing
    files = dict(setup.get("files", {}))
    routing = setup.get("routing", {})
    if routing and "/routing.json" not in files:
        files.update(make_routing_file(routing))
    
    return make_state(
        messages=messages,
        files=files,
        mode=setup.get("mode", "learn"),
        user_id=setup.get("user_id", "test_user"),
    )
