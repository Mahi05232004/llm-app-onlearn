"""Tests for learning_plan.py — pure helper functions (no MongoDB needed)."""

import pytest


class TestFormatPlanAsMarkdown:
    """_format_plan_as_markdown() should produce readable checklist output."""

    def test_formats_basic_plan(self):
        from app.tutor.core.tools.learning_plan import _format_plan_as_markdown

        plan = {
            "total_topics": 3,
            "total_weeks": 1,
            "weeks": [
                {
                    "week_number": 1,
                    "focus_area": "Arrays & Hashing",
                    "status": "in_progress",
                    "topics": [
                        {"title": "Two Sum", "difficulty": "Easy", "question_id": "q_1", "status": "completed"},
                        {"title": "Contains Duplicate", "difficulty": "Easy", "question_id": "q_2", "status": "in_progress"},
                        {"title": "Group Anagrams", "difficulty": "Medium", "question_id": "q_3", "status": "not_started"},
                    ],
                },
            ],
        }

        result = _format_plan_as_markdown(plan, "dsa")

        assert "# Learning Plan (DSA)" in result
        assert "**Total Topics:** 3" in result
        assert "## Week 1: Arrays & Hashing" in result
        assert "- [x] Two Sum" in result   # completed
        assert "- [ ] Contains Duplicate" in result  # in_progress (not checked)
        assert "- [ ] Group Anagrams" in result  # not_started

    def test_empty_plan(self):
        from app.tutor.core.tools.learning_plan import _format_plan_as_markdown

        plan = {"total_topics": 0, "weeks": []}
        result = _format_plan_as_markdown(plan, "ds")
        assert "# Learning Plan (DS)" in result
        assert "**Total Topics:** 0" in result

    def test_multiple_weeks(self):
        from app.tutor.core.tools.learning_plan import _format_plan_as_markdown

        plan = {
            "total_topics": 2,
            "total_weeks": 2,
            "weeks": [
                {"week_number": 1, "focus_area": "Arrays", "status": "completed", "topics": [
                    {"title": "Two Sum", "difficulty": "Easy", "question_id": "q_1", "status": "completed"},
                ]},
                {"week_number": 2, "focus_area": "Trees", "status": "not_started", "topics": [
                    {"title": "Invert Tree", "difficulty": "Easy", "question_id": "q_10", "status": "not_started"},
                ]},
            ],
        }

        result = _format_plan_as_markdown(plan, "dsa")
        assert "Week 1: Arrays" in result
        assert "Week 2: Trees" in result

    def test_includes_question_id(self):
        from app.tutor.core.tools.learning_plan import _format_plan_as_markdown

        plan = {
            "total_topics": 1,
            "weeks": [{"week_number": 1, "focus_area": "Test", "status": "not_started", "topics": [
                {"title": "Test Q", "difficulty": "Easy", "question_id": "q_test_123", "status": "not_started"},
            ]}],
        }

        result = _format_plan_as_markdown(plan, "dsa")
        assert "q_test_123" in result


class TestExtractUserAndModule:
    """_extract_user_and_module() should pull user_id and module from config."""

    def test_extracts_from_config(self):
        from app.tutor.core.tools.learning_plan import _extract_user_and_module

        config = {"configurable": {"assistant_id": "user_abc", "module": "ds"}}
        user_id, module = _extract_user_and_module(config)
        assert user_id == "user_abc"
        assert module == "ds"

    def test_defaults_to_dsa_and_empty(self):
        from app.tutor.core.tools.learning_plan import _extract_user_and_module

        config = {"configurable": {}}
        user_id, module = _extract_user_and_module(config)
        assert user_id == ""
        assert module == "dsa"

    def test_handles_missing_configurable(self):
        from app.tutor.core.tools.learning_plan import _extract_user_and_module

        config = {}
        user_id, module = _extract_user_and_module(config)
        assert user_id == ""
        assert module == "dsa"
