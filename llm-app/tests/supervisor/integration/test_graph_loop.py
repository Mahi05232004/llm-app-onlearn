"""Integration tests for the graph loop mechanics with mock agents.

These tests verify that the graph correctly loops when agents
delegate or hand back, and terminates when no handoff occurs.
No LLM calls — all agents are mocked with scripted responses.
"""
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.supervisor.graph.state import OrchestratorState
from app.supervisor.agents.nodes import (
    create_master_node,
    create_concept_tutor_node,
    create_lab_mentor_node,
    _extract_routing_from_messages,
)
from tests.supervisor.conftest import (
    make_state,
    make_files,
    make_routing,
    make_routing_file,
    make_mock_agent,
    make_handback_tool_message,
    make_delegation_tool_message,
)


# ──────────────────────────────────────────────
# Helper: run a single node and inspect output
# ──────────────────────────────────────────────

async def run_node(node_fn, state: dict) -> dict:
    """Run a node function and return output state."""
    return await node_fn(state)


# ──────────────────────────────────────────────
# Node Wrapper Tests
# ──────────────────────────────────────────────

class TestMasterNodeSetsHandoffFlag:
    """Test that the master node sets pending_handoff when delegating."""
    
    @pytest.mark.asyncio
    async def test_delegation_sets_pending_handoff(self):
        """When master delegates, pending_handoff should be True in routing."""
        delegation_msg = make_delegation_tool_message(
            agent_name="concept_tutor",
            objective="Teach Arrays",
        )
        
        mock_agent = make_mock_agent([{
            "messages": [
                AIMessage(content="Let me get you started with Arrays!"),
                delegation_msg,
            ],
        }])
        
        node_fn = create_master_node(mock_agent)
        state = make_state(
            messages=[HumanMessage(content="I want to learn arrays")],
            files=make_files(routing=make_routing()),
        )
        
        with patch("app.supervisor.agents.nodes.handoff_module") as mock_handoff:
            mock_handoff._pending_routing = {}
            result = await run_node(node_fn, state)
        
        # Check that routing was updated with pending_handoff
        routing_file = result["files"].get("/routing.json", {})
        content = routing_file.get("content", "{}")
        routing = json.loads(content)
        assert routing.get("pending_handoff") is True
        assert routing.get("active_agent") == "concept_tutor"
    
    @pytest.mark.asyncio
    async def test_no_delegation_no_pending_handoff(self):
        """When master responds normally, no pending_handoff."""
        mock_agent = make_mock_agent([{
            "messages": [AIMessage(content="Hello! How can I help?")],
        }])
        
        node_fn = create_master_node(mock_agent)
        state = make_state(
            messages=[HumanMessage(content="Hi")],
            files=make_files(routing=make_routing()),
        )
        
        with patch("app.supervisor.agents.nodes.handoff_module") as mock_handoff:
            mock_handoff._pending_routing = {}
            result = await run_node(node_fn, state)
        
        # Routing should not have pending_handoff
        routing_file = result["files"].get("/routing.json", {})
        if routing_file:
            content = routing_file.get("content", "{}")
            routing = json.loads(content)
            assert routing.get("pending_handoff") is not True


class TestSubAgentNodeSetsHandoffFlag:
    """Test that sub-agent nodes set pending_handoff on handback."""
    
    @pytest.mark.asyncio
    async def test_concept_tutor_handback_sets_pending_handoff(self):
        """When concept tutor hands back, pending_handoff should be True."""
        handback_msg = make_handback_tool_message(
            reason="objective_complete",
            summary="Student understands the concept",
        )
        
        mock_agent = make_mock_agent([{
            "messages": [
                AIMessage(content="Great job understanding this!"),
                handback_msg,
            ],
        }])
        
        node_fn = create_concept_tutor_node(mock_agent)
        routing = make_routing(
            active_agent="concept_tutor",
            question_id="two-sum",
        )
        state = make_state(
            messages=[HumanMessage(content="I think I get it")],
            files=make_files(routing=routing, topic_id="two-sum"),
        )
        
        with patch("app.supervisor.agents.nodes.handoff_module") as mock_handoff:
            mock_handoff._pending_routing = {}
            with patch("app.supervisor.agents.nodes.get_question_by_id", return_value=None):
                result = await run_node(node_fn, state)
        
        routing_file = result["files"].get("/routing.json", {})
        content = routing_file.get("content", "{}")
        routing_out = json.loads(content)
        assert routing_out.get("pending_handoff") is True
        assert routing_out.get("active_agent") == "master"
    
    @pytest.mark.asyncio
    async def test_concept_tutor_normal_response_no_handoff(self):
        """When concept tutor responds normally, no pending_handoff."""
        mock_agent = make_mock_agent([{
            "messages": [AIMessage(content="Let me explain arrays...")],
        }])
        
        node_fn = create_concept_tutor_node(mock_agent)
        routing = make_routing(
            active_agent="concept_tutor",
            question_id="two-sum",
        )
        state = make_state(
            messages=[HumanMessage(content="Explain arrays")],
            files=make_files(routing=routing, topic_id="two-sum"),
        )
        
        with patch("app.supervisor.agents.nodes.handoff_module") as mock_handoff:
            mock_handoff._pending_routing = {}
            with patch("app.supervisor.agents.nodes.get_question_by_id", return_value=None):
                result = await run_node(node_fn, state)
        
        # Should not set pending_handoff
        routing_file = result["files"].get("/routing.json", {})
        if routing_file:
            content = routing_file.get("content", "{}")
            routing_out = json.loads(content)
            assert routing_out.get("pending_handoff") is not True
    
    @pytest.mark.asyncio
    async def test_lab_mentor_handback_sets_pending_handoff(self):
        """When lab mentor hands back, pending_handoff should be True."""
        handback_msg = make_handback_tool_message(
            reason="objective_complete",
            summary="Code is correct and passes all tests",
        )
        
        mock_agent = make_mock_agent([{
            "messages": [
                AIMessage(content="Your code passes all test cases!"),
                handback_msg,
            ],
        }])
        
        node_fn = create_lab_mentor_node(mock_agent)
        routing = make_routing(
            active_agent="lab_mentor",
            expected_mode="code",
            question_id="two-sum",
        )
        state = make_state(
            messages=[HumanMessage(content="Here's my solution")],
            mode="code",
            files=make_files(routing=routing, topic_id="two-sum"),
        )
        
        with patch("app.supervisor.agents.nodes.handoff_module") as mock_handoff:
            mock_handoff._pending_routing = {}
            with patch("app.supervisor.agents.nodes.get_question_by_id", return_value=None):
                result = await run_node(node_fn, state)
        
        routing_file = result["files"].get("/routing.json", {})
        content = routing_file.get("content", "{}")
        routing_out = json.loads(content)
        assert routing_out.get("pending_handoff") is True


class TestMasterClearsHandoffFields:
    """Test that Master clears handoff fields after processing them."""
    
    @pytest.mark.asyncio
    async def test_clears_handoff_summary_after_processing(self):
        """After Master processes a handback (and doesn't re-delegate),
        handoff_summary should be cleared from routing."""
        mock_agent = make_mock_agent([{
            "messages": [AIMessage(content="Great work! What's next?")],
        }])
        
        node_fn = create_master_node(mock_agent)
        routing = make_routing(
            active_agent="master",
            handoff_summary="Student completed Two Sum",
            handoff_reason="objective_complete",
        )
        state = make_state(
            messages=[HumanMessage(content="Done!")],
            files=make_files(routing=routing),
        )
        
        with patch("app.supervisor.agents.nodes.handoff_module") as mock_handoff:
            mock_handoff._pending_routing = {}
            result = await run_node(node_fn, state)
        
        routing_file = result["files"].get("/routing.json", {})
        content = routing_file.get("content", "{}")
        routing_out = json.loads(content)
        # Handoff fields should be cleared
        assert "handoff_summary" not in routing_out
        assert "handoff_reason" not in routing_out


class TestExtractRoutingFromMessages:
    """Test the routing extraction helper."""
    
    def test_extracts_delegation(self):
        msg = make_delegation_tool_message(agent_name="lab_mentor")
        result = _extract_routing_from_messages([msg])
        assert result is not None
        assert result["active_agent"] == "lab_mentor"
    
    def test_extracts_handback(self):
        msg = make_handback_tool_message(reason="needs_help")
        result = _extract_routing_from_messages([msg])
        assert result is not None
        assert result["active_agent"] == "master"
    
    def test_returns_none_for_normal_messages(self):
        msgs = [AIMessage(content="Hello")]
        assert _extract_routing_from_messages(msgs) is None
    
    def test_returns_last_routing(self):
        """When multiple routing messages exist, return the last one."""
        msg1 = make_delegation_tool_message(agent_name="concept_tutor")
        msg2 = make_delegation_tool_message(agent_name="lab_mentor")
        # reversed() in the actual code means last message is checked first
        result = _extract_routing_from_messages([msg1, msg2])
        assert result["active_agent"] == "lab_mentor"
