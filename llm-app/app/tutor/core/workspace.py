"""Tutor workspace initialization — seeds memory files for new students."""
import logging
import pathlib
from datetime import datetime, timezone
from langgraph.store.base import BaseStore

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"


def _create_file_data(content: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "content": content.split("\n"),
        "created_at": now,
        "modified_at": now,
    }


async def initialize_tutor_workspace(store: BaseStore, user_id: str) -> None:
    """Seed a new student's workspace with template memory files.

    Idempotent — only creates files if /AGENTS.md does not already exist.
    Seeds: /AGENTS.md and /short_term_plan.md

    IMPORTANT: Keys use leading slash (e.g. '/AGENTS.md') to match the paths
    in the agent memory=[] list and StoreBackend.read_file('/AGENTS.md').
    Skills are loaded from disk via CompositeBackend — no seeding needed.
    Global plan is accessed via tools — no file sync needed.
    """
    namespace = (user_id,)

    # Check if already initialized with the correct leading-slash key
    try:
        existing = await store.aget(namespace, "/AGENTS.md")
        if existing:
            return
    except Exception:
        pass

    # Migration: check for old bare-key entries (seeded before the slash fix)
    try:
        old_agents = await store.aget(namespace, "AGENTS.md")
        old_plan = await store.aget(namespace, "short_term_plan.md")
        if old_agents:
            logger.info(f"[Workspace] Migrating bare-key store entries to slash-prefix for user {user_id}")
            await store.aput(namespace, "/AGENTS.md", old_agents.value)
            if old_plan:
                await store.aput(namespace, "/short_term_plan.md", old_plan.value)
            else:
                await store.aput(namespace, "/short_term_plan.md", _create_file_data("# Short Term Plan\nNo plan yet."))
            return
    except Exception:
        pass

    # Seed fresh memory files with leading-slash keys
    try:
        agents_md = (_TEMPLATES_DIR / "AGENTS.md").read_text()
        await store.aput(namespace, "/AGENTS.md", _create_file_data(agents_md))
        await store.aput(namespace, "/short_term_plan.md", _create_file_data("# Short Term Plan\nNo plan yet."))
        logger.info(f"[Workspace] Initialized workspace for user {user_id}")
    except Exception as e:
        logger.warning(f"[Workspace] Failed to seed workspace for {user_id}: {e}")

