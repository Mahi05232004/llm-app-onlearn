"""Tests for workspace initialization — seeding memory files."""

import pytest
import pytest_asyncio


@pytest.mark.asyncio
class TestWorkspaceInit:
    """initialize_tutor_workspace() should seed all required memory files."""

    async def test_seeds_all_memory_files(self, in_memory_store, test_user_id):
        """Both initial memory files should be created."""
        from app.tutor.core.workspace import initialize_tutor_workspace

        await initialize_tutor_workspace(in_memory_store, test_user_id)

        namespace = (test_user_id,)
        agents_md = await in_memory_store.aget(namespace, "/AGENTS.md")
        plan = await in_memory_store.aget(namespace, "/short_term_plan.md")

        assert agents_md is not None, "AGENTS.md should be seeded"
        assert plan is not None, "short_term_plan.md should be seeded"

    async def test_agents_md_has_template_sections(self, in_memory_store, test_user_id):
        """AGENTS.md should contain template sections matching update_student_notes categories."""
        from app.tutor.core.workspace import initialize_tutor_workspace

        await initialize_tutor_workspace(in_memory_store, test_user_id)

        result = await in_memory_store.aget((test_user_id,), "/AGENTS.md")
        content = "\n".join(result.value.get("content", []))
        assert "# Student Profile" in content
        assert "# Learning Observations" in content
        assert "# Milestones" in content

    async def test_idempotent_does_not_overwrite(self, in_memory_store, test_user_id):
        """Calling init twice should NOT overwrite existing files."""
        from app.tutor.core.workspace import initialize_tutor_workspace

        # First init
        await initialize_tutor_workspace(in_memory_store, test_user_id)

        # Modify AGENTS.md with custom content
        custom = {"content": ["# Custom student notes"], "created_at": "", "modified_at": ""}
        await in_memory_store.aput((test_user_id,), "/AGENTS.md", custom)

        # Second init — should detect existing AGENTS.md and skip
        await initialize_tutor_workspace(in_memory_store, test_user_id)

        result = await in_memory_store.aget((test_user_id,), "/AGENTS.md")
        assert result.value["content"] == ["# Custom student notes"], \
            "Second init should NOT overwrite custom content"

    async def test_short_term_plan_has_default(self, in_memory_store, test_user_id):
        """short_term_plan.md should have a sensible default."""
        from app.tutor.core.workspace import initialize_tutor_workspace

        await initialize_tutor_workspace(in_memory_store, test_user_id)

        result = await in_memory_store.aget((test_user_id,), "/short_term_plan.md")
        content = "\n".join(result.value.get("content", []))
        assert "plan" in content.lower(), "Default plan should mention 'plan'"

    async def test_file_metadata_includes_timestamps(self, in_memory_store, test_user_id):
        """Seeded files should have created_at and modified_at timestamps."""
        from app.tutor.core.workspace import initialize_tutor_workspace

        await initialize_tutor_workspace(in_memory_store, test_user_id)

        result = await in_memory_store.aget((test_user_id,), "/AGENTS.md")
        assert "created_at" in result.value, "File should have created_at"
        assert "modified_at" in result.value, "File should have modified_at"
