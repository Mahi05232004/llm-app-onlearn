"""
Scenario runner — replays captured YAML scenarios as pytest tests.

Two test levels:
  1. Router tests (fast): Validates which agent the router picks for a given state
  2. Node replay tests (async): Replays through real node wrappers with mock agents,
     verifying routing/handoff behavior matches expectations

Scenarios are YAML files in tests/supervisor/scenarios/captured/*.yaml.

Usage:
    pytest tests/supervisor/scenarios/ -v
    pytest tests/supervisor/scenarios/runner.py -v -k "handback"
"""
import json
import glob
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.supervisor.graph.router import router, post_agent_router
from app.supervisor.agents.nodes import (
    create_master_node,
    create_concept_tutor_node,
    create_lab_mentor_node,
)
from tests.supervisor.conftest import (
    make_state,
    make_files,
    make_routing,
    make_routing_file,
    make_mock_agent,
    build_state_from_scenario,
)


SCENARIOS_DIR = Path(__file__).parent / "captured"


def load_scenarios() -> list[dict]:
    """Load all YAML scenario files."""
    files = sorted(glob.glob(str(SCENARIOS_DIR / "*.yaml")))
    scenarios = []
    for f in files:
        with open(f) as fh:
            data = yaml.safe_load(fh)
            if data:
                data["_file"] = f
                scenarios.append(data)
    return scenarios


def scenario_ids(scenarios: list[dict]) -> list[str]:
    """Generate test IDs from scenario names."""
    return [s.get("name", f"scenario_{i}") for i, s in enumerate(scenarios)]


def _get_node_fn_for_agent(agent_name: str, mock_agent):
    """Create the correct node wrapper for an agent name."""
    if agent_name == "master":
        return create_master_node(mock_agent)
    elif agent_name == "concept_tutor":
        return create_concept_tutor_node(mock_agent)
    elif agent_name == "lab_mentor":
        return create_lab_mentor_node(mock_agent)
    else:
        raise ValueError(f"Unknown agent: {agent_name}")


def _build_mock_messages_from_actual(actual: dict) -> list:
    """Build mock agent response messages from a scenario's 'actual' section."""
    messages = []
    
    response = actual.get("response", "")
    if response:
        # Check if agent made tool calls
        tool_calls = []
        for event in actual.get("tool_events", []):
            tool_name = event.get("tool", "")
            output_preview = event.get("output_preview", "")
            if tool_name:
                tool_calls.append({
                    "name": tool_name,
                    "args": {},
                    "id": f"replay_{tool_name}",
                    "type": "tool_call",
                })
        
        if tool_calls:
            messages.append(AIMessage(content=response, tool_calls=tool_calls))
            # Add corresponding ToolMessages
            for tc in tool_calls:
                # For routing tools, reconstruct the routing JSON from actual output
                tool_output = "{}"
                if tc["name"] == "hand_back_to_master":
                    routing_after = actual.get("routing_after", {})
                    tool_output = json.dumps({
                        "action": "hand_back_to_master",
                        "routing": routing_after,
                    })
                elif tc["name"] == "delegate_to_agent":
                    routing_after = actual.get("routing_after", {})
                    tool_output = json.dumps({
                        "action": "delegate_to_agent",
                        "routing": routing_after,
                    })
                messages.append(ToolMessage(
                    content=tool_output,
                    tool_call_id=tc["id"],
                ))
        else:
            messages.append(AIMessage(content=response))
    else:
        messages.append(AIMessage(content="Mock response"))
    
    return messages


def _parse_routing_from_result(result: dict) -> dict:
    """Extract routing dict from a node result's files."""
    routing_file = result.get("files", {}).get("/routing.json", {})
    content = routing_file.get("content", "{}")
    if isinstance(content, str):
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


# ──────────────────────────────────────────────
# Level 1: Router Decision Tests (fast, sync)
# ──────────────────────────────────────────────

_scenarios = load_scenarios()


class TestScenarioRouting:
    """Validate that the router picks the correct agent for each scenario's state."""

    @pytest.mark.parametrize("scenario", _scenarios, ids=scenario_ids(_scenarios))
    def test_initial_routing(self, scenario):
        expect = scenario.get("expect", {})
        if "initial_agent" not in expect:
            pytest.skip("No 'initial_agent' expectation defined")

        state = build_state_from_scenario(scenario)
        agent = router(state)
        assert agent == expect["initial_agent"], (
            f"Scenario '{scenario.get('name')}': "
            f"Expected router to pick '{expect['initial_agent']}', got '{agent}'"
        )


# ──────────────────────────────────────────────
# Level 2: Node Replay Tests (async, with mocks)
# ──────────────────────────────────────────────

class TestScenarioReplay:
    """Replay scenarios through real node wrappers with mock agents.
    
    Tests that the node wrappers correctly handle routing updates,
    handoff flags, and state persistence — using the captured actual
    output as the mock agent's response.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", _scenarios, ids=scenario_ids(_scenarios))
    async def test_node_replay(self, scenario):
        actual = scenario.get("actual", {})
        expect = scenario.get("expect", {})
        agent_name = actual.get("agent", "")
        
        if not agent_name:
            pytest.skip("No agent in actual output")
        
        if not any(k in expect for k in ("has_handoff", "routing_after", "no_tools")):
            pytest.skip("No replay expectations defined (need has_handoff, routing_after, or no_tools)")
        
        # Build state from the scenario setup
        state = build_state_from_scenario(scenario)
        
        # Build mock agent that returns the captured actual output
        mock_messages = _build_mock_messages_from_actual(actual)
        mock_agent = make_mock_agent([{"messages": mock_messages}])
        
        # Create the node wrapper for this agent
        node_fn = _get_node_fn_for_agent(agent_name, mock_agent)
        
        # Run through the real node wrapper
        with patch("app.supervisor.agents.nodes.handoff_module") as mock_handoff:
            mock_handoff._pending_routing = {}
            with patch("app.supervisor.agents.nodes.get_question_by_id", return_value=None):
                result = await node_fn(state)
        
        # Assert expectations
        routing_out = _parse_routing_from_result(result)
        
        if "has_handoff" in expect:
            actual_handoff = routing_out.get("pending_handoff", False)
            expected_handoff = expect["has_handoff"]
            assert actual_handoff == expected_handoff, (
                f"Scenario '{scenario.get('name')}': "
                f"Expected pending_handoff={expected_handoff}, got {actual_handoff}"
            )
        
        if "routing_after" in expect:
            expected_routing = expect["routing_after"]
            for key, expected_val in expected_routing.items():
                actual_val = routing_out.get(key)
                assert actual_val == expected_val, (
                    f"Scenario '{scenario.get('name')}': "
                    f"Expected routing['{key}']={expected_val!r}, got {actual_val!r}"
                )


# ──────────────────────────────────────────────
# Structural test
# ──────────────────────────────────────────────

def test_scenarios_directory_exists():
    """Verify the scenarios directory structure exists."""
    assert SCENARIOS_DIR.parent.exists(), "scenarios/ directory missing"
    assert SCENARIOS_DIR.exists(), "scenarios/captured/ directory missing"
