"""Unit tests for the graph router and post_agent_router."""
import json
import pytest

from app.supervisor.graph.router import router, post_agent_router, MAX_ITERATIONS

# We import the factories from conftest (auto-discovered by pytest)
from tests.supervisor.conftest import make_routing, make_files, make_state


class TestRouter:
    """Tests for the initial entry router."""
    
    def test_routes_to_master_by_default(self):
        state = make_state(files=make_files())
        assert router(state) == "master"
    
    def test_routes_to_concept_tutor(self):
        routing = make_routing(active_agent="concept_tutor")
        state = make_state(files=make_files(routing=routing))
        assert router(state) == "concept_tutor"
    
    def test_routes_to_lab_mentor(self):
        routing = make_routing(active_agent="lab_mentor")
        state = make_state(files=make_files(routing=routing))
        assert router(state) == "lab_mentor"
    
    def test_mode_mismatch_returns_to_master(self):
        """If student switched modes, always route to master."""
        routing = make_routing(
            active_agent="concept_tutor",
            expected_mode="learn",
        )
        state = make_state(
            mode="code",  # student switched to code mode
            files=make_files(routing=routing),
        )
        assert router(state) == "master"
    
    def test_no_mode_mismatch_routes_normally(self):
        routing = make_routing(
            active_agent="lab_mentor",
            expected_mode="code",
        )
        state = make_state(
            mode="code",
            files=make_files(routing=routing),
        )
        assert router(state) == "lab_mentor"
    
    def test_unknown_agent_defaults_to_master(self):
        routing = make_routing(active_agent="unknown_agent")
        state = make_state(files=make_files(routing=routing))
        assert router(state) == "master"
    
    def test_empty_files_routes_to_master(self):
        state = make_state(files={})
        assert router(state) == "master"


class TestPostAgentRouter:
    """Tests for the post-agent loop decision."""
    
    def test_no_handoff_returns_end(self):
        routing = make_routing(active_agent="master")
        state = make_state(files=make_files(routing=routing))
        assert post_agent_router(state) == "__end__"
    
    def test_pending_handoff_returns_router(self):
        routing = make_routing(
            active_agent="master",
            pending_handoff=True,
        )
        state = make_state(files=make_files(routing=routing))
        assert post_agent_router(state) == "router"
    
    def test_max_iterations_forces_end(self):
        routing = make_routing(
            active_agent="master",
            pending_handoff=True,
        )
        state = make_state(
            files=make_files(routing=routing),
            iteration=MAX_ITERATIONS,
        )
        assert post_agent_router(state) == "__end__"
    
    def test_max_iterations_boundary(self):
        """At exactly MAX_ITERATIONS - 1, should still loop."""
        routing = make_routing(
            active_agent="concept_tutor",
            pending_handoff=True,
        )
        state = make_state(
            files=make_files(routing=routing),
            iteration=MAX_ITERATIONS - 1,
        )
        assert post_agent_router(state) == "router"
    
    def test_empty_routing_returns_end(self):
        state = make_state(files={})
        assert post_agent_router(state) == "__end__"
    
    def test_handoff_false_returns_end(self):
        """Explicitly false pending_handoff should exit."""
        routing = make_routing(active_agent="master")
        routing["pending_handoff"] = False
        state = make_state(files=make_files(routing=routing))
        assert post_agent_router(state) == "__end__"
