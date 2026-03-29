"""Tests for tutor agent creation — verifies factory functions produce valid agents.

NOTE: These tests mock MongoDB because the agent import chain loads
`core.mongo_db` which attempts to connect at import time.
"""

import sys
import pytest
from unittest.mock import MagicMock, patch


# ── Mock MongoDB before importing agent modules ─────────────────────
# The agent import chain: agent.py → tools/get_cross_mode_code.py → core/mongo_db.py
# mongo_db.py creates a MongoDatabaseManager() at module level which pings MongoDB.
# We need to mock this before the import happens.

def _mock_mongo_modules():
    """Pre-populate sys.modules with mocked MongoDB so imports don't fail."""
    mock_mongo = MagicMock()
    mock_mongo.MongoDatabaseManager.return_value = MagicMock()
    mock_mongo.mongo_db_manager = MagicMock()
    # Only set if not already loaded
    if "core.mongo_db" not in sys.modules:
        sys.modules["core.mongo_db"] = mock_mongo


class TestDSAAgentCreation:
    """Verify create_dsa_agent() produces a valid compiled graph."""

    def test_creates_compiled_graph(self):
        """create_dsa_agent() returns a CompiledStateGraph."""
        _mock_mongo_modules()
        from app.tutor.dsa.agent import create_dsa_agent

        mock_model = MagicMock()
        mock_model.with_config = MagicMock(return_value=mock_model)

        agent = create_dsa_agent(model=mock_model)

        # Should return a compiled graph (CompiledStateGraph)
        assert agent is not None
        assert hasattr(agent, "ainvoke"), "Agent must support ainvoke()"
        assert hasattr(agent, "astream_events"), "Agent must support astream_events()"

    def test_agent_has_expected_tools(self):
        """Agent should have get_cross_mode_code and search_history tools."""
        _mock_mongo_modules()
        from app.tutor.dsa.agent import create_dsa_agent

        mock_model = MagicMock()
        mock_model.with_config = MagicMock(return_value=mock_model)

        agent = create_dsa_agent(model=mock_model)

        # Check the agent graph has tool nodes
        node_names = list(agent.get_graph().nodes.keys())
        assert "tools" in node_names, f"'tools' node missing. Nodes: {node_names}"


class TestDSAgentCreation:
    """Verify create_ds_agent() produces a valid compiled graph."""

    def test_creates_compiled_graph(self):
        """create_ds_agent() returns a CompiledStateGraph."""
        _mock_mongo_modules()
        from app.tutor.ds.agent import create_ds_agent

        mock_model = MagicMock()
        mock_model.with_config = MagicMock(return_value=mock_model)

        agent = create_ds_agent(model=mock_model)

        assert agent is not None
        assert hasattr(agent, "ainvoke")
        assert hasattr(agent, "astream_events")


class TestOnboardingAgentCreation:
    """Verify onboarding agent can be built."""

    def test_build_onboarding_graph(self):
        """_build_onboarding_graph() returns a valid StateGraph."""
        _mock_mongo_modules()
        from app.onboarding.agent import _build_onboarding_graph

        graph = _build_onboarding_graph("You are an onboarding agent.")

        assert graph is not None
        # It should have chatbot and tools nodes
        node_names = list(graph.nodes.keys())
        assert "chatbot" in node_names
        assert "tools" in node_names
