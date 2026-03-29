"""Tests for TutorContextMiddleware — context formatting and injection."""

import pytest

from app.tutor.core.context_middleware import (
    format_tutor_context,
    _format_question_context,
    _format_time_section,
)



class TestFormatTutorContext:
    """format_tutor_context() should produce mode-aware context strings."""

    def test_learn_mode_includes_learn_ui(self, sample_tutor_context):
        """Learn mode should include learn-mode UI description."""
        result = format_tutor_context(sample_tutor_context)
        assert "Learn Mode" in result
        assert "Main Chat Interface" in result

    def test_code_mode_includes_code_ui(self, sample_tutor_context):
        """Code mode should include code-mode UI description."""
        sample_tutor_context["mode"] = "code"
        result = format_tutor_context(sample_tutor_context)
        assert "Code Mode" in result
        assert "Code Editor" in result

    def test_includes_module_name(self, sample_tutor_context):
        """Should include the full module name."""
        result = format_tutor_context(sample_tutor_context)
        assert "Data Structures & Algorithms" in result

    def test_ds_module_name(self, sample_tutor_context):
        """DS module should show 'Data Science & Machine Learning'."""
        sample_tutor_context["module"] = "ds"
        result = format_tutor_context(sample_tutor_context)
        assert "Data Science" in result

    def test_includes_question_title(self, sample_tutor_context):
        """Should include the question title from question_data."""
        result = format_tutor_context(sample_tutor_context)
        assert "Two Sum" in result


    def test_includes_time_section(self, sample_tutor_context):
        """Should include current time information."""
        result = format_tutor_context(sample_tutor_context)
        assert "Current Time" in result




class TestFormatQuestionContext:
    """_format_question_context() should format question fields."""

    def test_includes_title_and_difficulty(self, sample_question_data):
        result = _format_question_context(sample_question_data)
        assert "Two Sum" in result
        assert "easy" in result

    def test_includes_concepts(self, sample_question_data):
        result = _format_question_context(sample_question_data)
        assert "hash map" in result

    def test_includes_problem_statement(self, sample_question_data):
        result = _format_question_context(sample_question_data)
        assert "array of integers" in result



    def test_minimal_question_data(self):
        """Should handle question data with only a title."""
        result = _format_question_context({"question_title": "Simple Q"})
        assert "Simple Q" in result





class TestFormatTimeSection:
    """_format_time_section() should handle time gaps."""

    def test_no_last_interaction(self):
        """Without last_interaction_at, no time gap note."""
        result = _format_time_section(None)
        assert "Current Time" in result
        assert "Last interaction" not in result

    def test_recent_interaction_no_gap(self):
        """Recent interaction (< 1 hour) should not show time gap."""
        from datetime import datetime, timezone, timedelta

        recent = datetime.now(timezone.utc) - timedelta(minutes=30)
        result = _format_time_section(recent)
        assert "Last interaction" not in result

    def test_old_interaction_shows_gap(self):
        """Old interaction (> 1 hour) should show time gap."""
        from datetime import datetime, timezone, timedelta

        old = datetime.now(timezone.utc) - timedelta(hours=10)
        result = _format_time_section(old)
        assert "Last interaction" in result
        assert "hours" in result

    def test_very_old_interaction_shows_days(self):
        """Very old interaction (> 24 hours) should show days."""
        from datetime import datetime, timezone, timedelta

        very_old = datetime.now(timezone.utc) - timedelta(days=3)
        result = _format_time_section(very_old)
        assert "days" in result
