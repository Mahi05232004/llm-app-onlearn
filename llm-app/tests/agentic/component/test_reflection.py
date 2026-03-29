"""Tests for reflection.py — background reflection helpers (no LLM needed)."""

import pytest
import pytest_asyncio

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage


# ── Test _format_messages ────────────────────────────────────────────


class TestFormatMessages:
    """_format_messages() should produce readable conversation text."""

    def test_formats_human_and_ai(self):
        from app.tutor.core.reflection import _format_messages

        messages = [
            HumanMessage(content="What is a hash map?"),
            AIMessage(content="A hash map is a data structure..."),
        ]
        result = _format_messages(messages)
        assert "Student:" in result
        assert "hash map" in result
        assert "Tutor:" in result
        assert "data structure" in result

    def test_includes_tool_messages(self):
        from app.tutor.core.reflection import _format_messages

        messages = [
            HumanMessage(content="hello"),
            ToolMessage(content="tool output", tool_call_id="abc"),
            AIMessage(content="world"),
        ]
        result = _format_messages(messages)
        assert "tool output" in result
        assert "hello" in result
        assert "world" in result

    def test_empty_messages(self):
        from app.tutor.core.reflection import _format_messages

        result = _format_messages([])
        assert result == "" or result.strip() == ""


# ── Test _read_store_file ────────────────────────────────────────────


@pytest.mark.asyncio
class TestReadStoreFile:
    """_read_store_file() should read content from the store."""

    async def test_reads_existing_file(self, in_memory_store, test_user_id):
        from app.tutor.core.reflection import _read_store_file

        await in_memory_store.aput(
            (test_user_id,), "AGENTS.md",
            {"content": ["# Student Profile", "- Some note"], "created_at": "", "modified_at": ""},
        )

        result = await _read_store_file(in_memory_store, (test_user_id,), "AGENTS.md")
        assert result is not None
        assert "Student Profile" in result

    async def test_returns_none_for_missing_file(self, in_memory_store, test_user_id):
        from app.tutor.core.reflection import _read_store_file

        result = await _read_store_file(in_memory_store, (test_user_id,), "nonexistent.md")
        assert result is None


# ── Test _apply_agents_md_updates ────────────────────────────────────


@pytest.mark.asyncio
class TestApplyAgentsMdUpdates:
    """_apply_agents_md_updates() should append observations to AGENTS.md."""

    async def test_appends_observation(self, in_memory_store, test_user_id):
        from app.tutor.core.reflection import _apply_agents_md_updates

        # Seed AGENTS.md
        await in_memory_store.aput(
            (test_user_id,), "AGENTS.md",
            {"content": ["# Student Profile", "# Learning Observations", "# Milestones"],
             "created_at": "", "modified_at": ""},
        )

        additions = [
            {"category": "strength", "observation": "Good at arrays"},
        ]

        await _apply_agents_md_updates(in_memory_store, (test_user_id,), additions)

        item = await in_memory_store.aget((test_user_id,), "AGENTS.md")
        content = "\n".join(item.value["content"])
        assert "Good at arrays" in content

    async def test_skips_empty_additions(self, in_memory_store, test_user_id):
        from app.tutor.core.reflection import _apply_agents_md_updates

        await in_memory_store.aput(
            (test_user_id,), "AGENTS.md",
            {"content": ["# Student Profile"], "created_at": "", "modified_at": ""},
        )

        # Should not error on empty list
        await _apply_agents_md_updates(in_memory_store, (test_user_id,), [])

        item = await in_memory_store.aget((test_user_id,), "AGENTS.md")
        assert item is not None


# ── Test _apply_plan_update ──────────────────────────────────────────


@pytest.mark.asyncio
class TestApplyPlanUpdate:
    """_apply_plan_update() should update short_term_plan.md."""

    async def test_updates_plan(self, in_memory_store, test_user_id):
        from app.tutor.core.reflection import _apply_plan_update

        await in_memory_store.aput(
            (test_user_id,), "short_term_plan.md",
            {"content": ["# Short Term Plan", "No plan yet."], "created_at": "", "modified_at": ""},
        )

        new_plan = "# Short Term Plan\n- [x] Learn hash maps\n- [ ] Practice Two Sum"
        await _apply_plan_update(in_memory_store, (test_user_id,), new_plan)

        item = await in_memory_store.aget((test_user_id,), "short_term_plan.md")
        content = "\n".join(item.value["content"])
        assert "Learn hash maps" in content

    async def test_none_plan_is_noop(self, in_memory_store, test_user_id):
        from app.tutor.core.reflection import _apply_plan_update

        await in_memory_store.aput(
            (test_user_id,), "short_term_plan.md",
            {"content": ["# Original Plan"], "created_at": "", "modified_at": ""},
        )

        await _apply_plan_update(in_memory_store, (test_user_id,), None)

        item = await in_memory_store.aget((test_user_id,), "short_term_plan.md")
        content = "\n".join(item.value["content"])
        assert "Original Plan" in content
