"""Unit tests for planner tools with mocked PlanningService."""
import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, UTC

from tests.supervisor.conftest import SAMPLE_STUDENT_PROFILE, SAMPLE_TOPIC


@pytest.fixture
def plan_data():
    """Sample plan data dict as the planner tools would receive."""
    return {
        "plan": {
            "weeks": [
                {
                    "week_number": 1,
                    "focus_area": "Arrays",
                    "topics": [
                        {
                            "question_id": "two-sum",
                            "title": "Two Sum",
                            "difficulty": "easy",
                            "status": "not_started",
                            "estimated_minutes": 30,
                        },
                        {
                            "question_id": "best-time-to-buy-and-sell-stock",
                            "title": "Best Time to Buy and Sell Stock",
                            "difficulty": "medium",
                            "status": "not_started",
                            "estimated_minutes": 45,
                        },
                    ],
                }
            ],
            "total_weeks": 3,
            "total_topics": 6,
        },
        "profile": SAMPLE_STUDENT_PROFILE,
        "progress": {
            "completed_topics": 0,
            "total_topics": 6,
            "completion_percentage": 0.0,
        },
        "started_at": datetime.now(UTC).isoformat(),
    }


@pytest.fixture
def mock_service():
    """Mock PlanningService."""
    service = MagicMock()
    return service


class TestMakeToolsFunctions:
    """Test that make_planner_tools returns callable tools."""
    
    def test_returns_five_tools(self, plan_data):
        from app.supervisor.planning.planner_tools import make_planner_tools
        tools = make_planner_tools(plan_data)
        assert len(tools) == 5
    
    def test_tool_names(self, plan_data):
        from app.supervisor.planning.planner_tools import make_planner_tools
        tools = make_planner_tools(plan_data)
        names = {t.name for t in tools}
        assert names == {
            "mark_topic_completed",
            "absorb_off_plan_topic",
            "adjust_schedule",
            "get_short_term_summary",
            "get_current_progress",
        }


class TestGetShortTermSummary:
    """Test the get_short_term_summary tool."""
    
    def test_returns_summary_dict(self, plan_data):
        from app.supervisor.planning.planner_tools import make_planner_tools
        tools = make_planner_tools(plan_data)
        summary_tool = next(t for t in tools if t.name == "get_short_term_summary")
        
        with patch("app.supervisor.planning.planner_tools.PlanningService") as MockService:
            mock_svc = MockService.return_value
            mock_svc.get_short_term_summary.return_value = {
                "current_week": 1,
                "current_focus": "Arrays",
                "next_topics": [{"question_id": "two-sum"}],
            }
            result = summary_tool.invoke({})
            assert "current_week" in result or "current_focus" in result


class TestGetCurrentProgress:
    """Test the get_current_progress tool."""
    
    def test_returns_progress(self, plan_data):
        from app.supervisor.planning.planner_tools import make_planner_tools
        tools = make_planner_tools(plan_data)
        progress_tool = next(t for t in tools if t.name == "get_current_progress")
        result = progress_tool.invoke({})
        # Should return the progress from plan_data
        assert isinstance(result, (dict, str))
