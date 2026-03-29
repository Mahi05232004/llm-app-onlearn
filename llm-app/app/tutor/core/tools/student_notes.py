"""Student notes tool — structured observation recording for AGENTS.md.

Provides a low-friction way for the agent to record observations about
the student during teaching, without needing to manually edit_file.

Uses InjectedToolArg to get store and config automatically — the agent
just calls update_student_notes(observation, category).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Literal

from langchain_core.tools import tool, InjectedToolArg
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

logger = logging.getLogger(__name__)

# Section headers in AGENTS.md that observations map to
SECTION_MAP = {
    "learning_style": "# Learning Observations",
    "struggle": "# Learning Observations",
    "strength": "# Learning Observations",
    "milestone": "# Milestones",
    "preference": "# Learning Observations",
}


async def _append_to_agents_md(
    store: BaseStore,
    user_id: str,
    category: str,
    observation: str,
) -> bool:
    """Append an observation to the appropriate section of AGENTS.md."""
    namespace = (user_id,)
    key = "AGENTS.md"

    try:
        item = await store.aget(namespace, key)
        if not item:
            logger.warning(f"AGENTS.md not found for user {user_id}")
            return False

        content_lines = item.value.get("content", [])
        content = "\n".join(content_lines) if isinstance(content_lines, list) else str(content_lines)

        # Find the target section and append after it
        target_header = SECTION_MAP.get(category, "# Learning Observations")
        today = datetime.now(timezone.utc).strftime("%b %d")
        entry = f"- [{today}] ({category}) {observation}"

        if target_header in content:
            # Insert after the header line (and any existing placeholder text)
            lines = content.split("\n")
            insert_idx = None
            for i, line in enumerate(lines):
                if line.strip() == target_header:
                    insert_idx = i + 1
                    # Skip placeholder lines (lines starting with _)
                    while insert_idx < len(lines) and lines[insert_idx].strip().startswith("_"):
                        insert_idx += 1
                    break

            if insert_idx is not None:
                lines.insert(insert_idx, entry)
                content = "\n".join(lines)
        else:
            # Section doesn't exist — append at end
            content += f"\n\n{target_header}\n{entry}"

        # Write back
        now = datetime.now(timezone.utc).isoformat()
        await store.aput(namespace, key, {
            "content": content.split("\n"),
            "created_at": item.value.get("created_at", now),
            "modified_at": now,
        })
        return True

    except Exception as e:
        logger.error(f"Failed to update AGENTS.md for user {user_id}: {e}", exc_info=True)
        return False


@tool(parse_docstring=True)
async def update_student_notes(
    observation: str,
    category: Literal[
        "learning_style",
        "struggle",
        "strength",
        "milestone",
        "preference",
    ],
    store: Annotated[BaseStore, InjectedToolArg()],
    config: Annotated[RunnableConfig, InjectedToolArg()],
) -> str:
    """Record an observation about the student for future reference.

    Use this whenever you notice something important about how the student
    learns, what they struggle with, or what they've achieved. These notes
    persist across all sessions and help you teach better.

    Args:
        observation: What you observed about the student, e.g. "Understood
            hash maps quickly after phone book analogy" or "Struggles with
            recursive thinking".
        category: The type of observation. One of learning_style (how they
            learn best), struggle (difficult concepts), strength (what
            they excel at), milestone (key achievements), or preference
            (code style, explanation depth, etc).
    """
    user_id = config.get("configurable", {}).get("assistant_id", "")
    if not user_id:
        return json.dumps({"status": "error", "message": "No user_id in config."})

    success = await _append_to_agents_md(store, user_id, category, observation)

    if success:
        return json.dumps({
            "status": "saved",
            "message": f"Noted ({category}): {observation}",
        })
    else:
        return json.dumps({
            "status": "error",
            "message": "Failed to save observation. AGENTS.md may not exist yet.",
        })
