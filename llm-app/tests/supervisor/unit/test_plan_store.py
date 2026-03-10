"""Unit tests for PlanStore with mocked MongoDB."""
import json
import pytest
from unittest.mock import MagicMock, patch

from app.supervisor.planning.plan_store import PlanStore


@pytest.fixture
def mock_collection():
    """Create a mock MongoDB collection."""
    return MagicMock()


@pytest.fixture
def store(mock_collection):
    """Create a PlanStore with a mocked collection."""
    with patch.object(PlanStore, '_get_collection', return_value=mock_collection):
        s = PlanStore()
        s._collection = mock_collection
        return s


class TestPlanStoreGetData:
    """Tests for PlanStore.get_plan_data."""
    
    def test_returns_plan_data(self, store, mock_collection):
        mock_collection.find_one.return_value = {
            "_id": "abc",
            "learningPlan": {"weeks": []},
            "progress": {"completed": 0},
            "studentProfile": {"goal": "learn DSA"},
            "shortTermPlan": {"current_week": 1},
        }
        result = store.get_plan_data("user123")
        mock_collection.find_one.assert_called_once()
        assert result["learningPlan"] == {"weeks": []}
        assert result["progress"] == {"completed": 0}
    
    def test_returns_empty_for_missing_user(self, store, mock_collection):
        mock_collection.find_one.return_value = None
        result = store.get_plan_data("nonexistent")
        assert result == {}
    
    def test_returns_empty_for_user_without_plan(self, store, mock_collection):
        mock_collection.find_one.return_value = {"_id": "abc"}
        result = store.get_plan_data("user123")
        # Should still return the doc (even without learningPlan)
        assert result is not None


class TestPlanStoreSaveData:
    """Tests for PlanStore.save_plan_data."""
    
    def test_saves_plan_progress_and_short_term(self, store, mock_collection):
        store.save_plan_data(
            user_id="user123",
            plan={"weeks": [{"week_number": 1}]},
            progress={"completed": 3},
            short_term={"current_week": 1},
        )
        mock_collection.update_one.assert_called_once()
        call_args = mock_collection.update_one.call_args
        update_dict = call_args[0][1]  # Second positional arg is the update
        assert "$set" in update_dict
        assert "learningPlan" in update_dict["$set"]
        assert "progress" in update_dict["$set"]
        assert "shortTermPlan" in update_dict["$set"]
