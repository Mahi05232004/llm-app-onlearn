"""Tests for student_notes.py — structured observation recording into AGENTS.md."""

import pytest
import pytest_asyncio

from app.tutor.core.tools.student_notes import _append_to_agents_md, SECTION_MAP


# Sample AGENTS.md template matching the real template
_SAMPLE_AGENTS_MD = """\
# Student Profile
_No observations yet._

# Learning Observations
_No observations yet._

# Milestones
_No milestones yet._
"""


@pytest.mark.asyncio
class TestAppendToAgentsMd:
    """_append_to_agents_md() should insert observations under correct sections."""

    async def test_appends_under_learning_observations(self, in_memory_store, test_user_id):
        """Observation should be inserted under # Learning Observations."""
        # Seed AGENTS.md
        await in_memory_store.aput(
            (test_user_id,), "AGENTS.md",
            {"content": _SAMPLE_AGENTS_MD.split("\n"), "created_at": "", "modified_at": ""}
        )

        result = await _append_to_agents_md(
            in_memory_store, test_user_id,
            category="struggle",
            observation="Has trouble with recursion",
        )
        assert result is True

        item = await in_memory_store.aget((test_user_id,), "AGENTS.md")
        content = "\n".join(item.value["content"])
        assert "Has trouble with recursion" in content
        assert "(struggle)" in content

    async def test_appends_milestone(self, in_memory_store, test_user_id):
        """Milestone category should go under # Milestones."""
        await in_memory_store.aput(
            (test_user_id,), "AGENTS.md",
            {"content": _SAMPLE_AGENTS_MD.split("\n"), "created_at": "", "modified_at": ""}
        )

        await _append_to_agents_md(
            in_memory_store, test_user_id,
            category="milestone",
            observation="Solved Two Sum independently",
        )

        item = await in_memory_store.aget((test_user_id,), "AGENTS.md")
        content = "\n".join(item.value["content"])
        assert "Solved Two Sum independently" in content
        assert "(milestone)" in content

    async def test_handles_missing_agents_md(self, in_memory_store, test_user_id):
        """Should return False if AGENTS.md doesn't exist."""
        result = await _append_to_agents_md(
            in_memory_store, test_user_id,
            category="strength",
            observation="Good at patterns",
        )
        assert result is False

    async def test_includes_date_stamp(self, in_memory_store, test_user_id):
        """Entry should include a date stamp like [Feb 28]."""
        await in_memory_store.aput(
            (test_user_id,), "AGENTS.md",
            {"content": _SAMPLE_AGENTS_MD.split("\n"), "created_at": "", "modified_at": ""}
        )

        await _append_to_agents_md(
            in_memory_store, test_user_id,
            category="learning_style",
            observation="Prefers visual explanations",
        )

        item = await in_memory_store.aget((test_user_id,), "AGENTS.md")
        content = "\n".join(item.value["content"])
        # Should contain a date like [Feb 28]
        assert "- [" in content

    async def test_appends_after_section_header(self, in_memory_store, test_user_id):
        """Multiple observations should accumulate, not overwrite."""
        await in_memory_store.aput(
            (test_user_id,), "AGENTS.md",
            {"content": _SAMPLE_AGENTS_MD.split("\n"), "created_at": "", "modified_at": ""}
        )

        await _append_to_agents_md(in_memory_store, test_user_id, "strength", "Fast learner")
        await _append_to_agents_md(in_memory_store, test_user_id, "struggle", "Slow with trees")

        item = await in_memory_store.aget((test_user_id,), "AGENTS.md")
        content = "\n".join(item.value["content"])
        assert "Fast learner" in content
        assert "Slow with trees" in content


class TestSectionMap:
    """SECTION_MAP should cover all valid categories."""

    def test_all_categories_mapped(self):
        """Every valid category should map to a section header."""
        expected_categories = {"learning_style", "struggle", "strength", "milestone", "preference"}
        assert set(SECTION_MAP.keys()) == expected_categories

    def test_milestone_maps_to_milestones(self):
        assert SECTION_MAP["milestone"] == "# Milestones"

    def test_learning_categories_map_to_observations(self):
        for cat in ("learning_style", "struggle", "strength", "preference"):
            assert SECTION_MAP[cat] == "# Learning Observations"
