"""Background reflection — async task that updates student profile and plans.

Triggered by the orchestrator every ~10 messages or on agent request.
Runs fire-and-forget — never blocks the student's response.

What it does:
  1. Reviews recent conversation (last ~10 messages from the thread)
  2. Updates /AGENTS.md with new observations about the student
  3. Updates /short_term_plan.md with progress
  4. Marks completed topics in the learning plan (via MongoDB)
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from langgraph.store.base import BaseStore

logger = logging.getLogger(__name__)

# Structured prompt for the reflection LLM call
_REFLECTION_PROMPT = """\
You are a teaching assistant reviewing a recent tutoring session. Analyze the conversation and produce a structured JSON update.

## Student's Current Profile (AGENTS.md):
{agents_md}

## Short-Term Plan:
{short_term_plan}

## Recent Conversation (last ~10 messages):
{recent_messages}

## Your Task:
Analyze the conversation and return a JSON object with these fields:

```json
{{
  "agents_md_additions": [
    {{"category": "learning_style|struggle|strength|milestone|preference", "observation": "..."}}
  ],
  "short_term_plan_update": "Updated markdown for short_term_plan.md, or null if no changes needed",
  "completed_topics": ["question_id_1", "question_id_2"],
  "summary": "One-line summary of what happened in this session"
}}
```

Rules:
- Only add observations that are NEW and not already in AGENTS.md
- Only mark topics complete if the student clearly solved them
- Keep observations concise (one line each)
- Return valid JSON only, no markdown fencing
"""


async def run_reflection(
    *,
    store: BaseStore,
    user_id: str,
    module: str,
    thread_id: str,
    agent,  # The compiled agent graph (to read thread state)
    model,  # LLM to use for reflection
) -> None:
    """Run background reflection on recent conversation.

    This is a fire-and-forget task — errors are logged but never raised.
    """
    try:
        logger.info(f"[Reflection] Starting for user={user_id}, thread={thread_id}")

        # 1. Read recent messages from the thread
        config = {"configurable": {"thread_id": thread_id, "assistant_id": user_id}}
        state = await agent.aget_state(config)
        all_messages = state.values.get("messages", [])

        if len(all_messages) < 4:
            logger.debug("[Reflection] Too few messages, skipping")
            return

        # Take last ~10 messages for analysis
        recent = all_messages[-10:]
        recent_text = _format_messages(recent)

        # 2. Read current AGENTS.md and short_term_plan.md
        namespace = (user_id,)
        agents_md_content = await _read_store_file(store, namespace, "AGENTS.md")
        plan_content = await _read_store_file(store, namespace, "short_term_plan.md")

        # 3. Call LLM for structured reflection
        prompt = _REFLECTION_PROMPT.format(
            agents_md=agents_md_content or "(empty)",
            short_term_plan=plan_content or "(empty)",
            recent_messages=recent_text,
        )

        response = await model.ainvoke(prompt)
        response_text = response.content if hasattr(response, "content") else str(response)

        # 4. Parse the structured response
        try:
            # Strip markdown code fences if present
            clean = response_text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1]
                if clean.endswith("```"):
                    clean = clean[:-3]
            updates = json.loads(clean)
        except json.JSONDecodeError:
            logger.warning(f"[Reflection] Failed to parse LLM response as JSON")
            return

        # 5. Apply updates
        await _apply_agents_md_updates(store, namespace, updates.get("agents_md_additions", []))
        await _apply_plan_update(store, namespace, updates.get("short_term_plan_update"))
        await _apply_completed_topics(user_id, module, updates.get("completed_topics", []))

        summary = updates.get("summary", "reflection complete")
        logger.info(f"[Reflection] Done for user={user_id}: {summary}")

    except Exception as e:
        logger.error(f"[Reflection] Failed for user={user_id}: {e}", exc_info=True)


def _format_messages(messages) -> str:
    """Format LangChain messages into readable text for the reflection prompt."""
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
    lines = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            lines.append(f"Student: {msg.content[:500]}")
        elif isinstance(msg, AIMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            lines.append(f"Tutor: {content[:500]}")
        elif isinstance(msg, ToolMessage):
            lines.append(f"[Tool result: {msg.content[:200]}]")
    return "\n".join(lines)


async def _read_store_file(store: BaseStore, namespace: tuple, key: str) -> str | None:
    """Read a file from the store, returning content as string or None."""
    try:
        item = await store.aget(namespace, key)
        if item and item.value:
            content = item.value.get("content", [])
            return "\n".join(content) if isinstance(content, list) else str(content)
    except Exception:
        pass
    return None


async def _apply_agents_md_updates(
    store: BaseStore,
    namespace: tuple,
    additions: list[dict],
) -> None:
    """Append new observations to AGENTS.md."""
    if not additions:
        return

    try:
        item = await store.aget(namespace, "AGENTS.md")
        if not item:
            return

        content_lines = item.value.get("content", [])
        content = "\n".join(content_lines) if isinstance(content_lines, list) else str(content_lines)

        today = datetime.now(timezone.utc).strftime("%b %d")

        section_map = {
            "learning_style": "# Learning Observations",
            "struggle": "# Learning Observations",
            "strength": "# Learning Observations",
            "milestone": "# Milestones",
            "preference": "# Learning Observations",
        }

        for addition in additions:
            category = addition.get("category", "learning_style")
            observation = addition.get("observation", "")
            if not observation:
                continue

            target_header = section_map.get(category, "# Learning Observations")
            entry = f"- [{today}] ({category}) {observation}"

            if target_header in content:
                lines = content.split("\n")
                for i, line in enumerate(lines):
                    if line.strip() == target_header:
                        insert_idx = i + 1
                        while insert_idx < len(lines) and lines[insert_idx].strip().startswith("_"):
                            insert_idx += 1
                        lines.insert(insert_idx, entry)
                        content = "\n".join(lines)
                        break
            else:
                content += f"\n\n{target_header}\n{entry}"

        now = datetime.now(timezone.utc).isoformat()
        await store.aput(namespace, "AGENTS.md", {
            "content": content.split("\n"),
            "created_at": item.value.get("created_at", now),
            "modified_at": now,
        })
        logger.debug(f"[Reflection] Updated AGENTS.md with {len(additions)} observations")

    except Exception as e:
        logger.error(f"[Reflection] Failed to update AGENTS.md: {e}")


async def _apply_plan_update(
    store: BaseStore,
    namespace: tuple,
    new_plan: str | None,
) -> None:
    """Update short_term_plan.md if the reflection produced changes."""
    if not new_plan:
        return

    try:
        now = datetime.now(timezone.utc).isoformat()
        await store.aput(namespace, "short_term_plan.md", {
            "content": new_plan.split("\n"),
            "created_at": now,
            "modified_at": now,
        })
        logger.debug("[Reflection] Updated short_term_plan.md")
    except Exception as e:
        logger.error(f"[Reflection] Failed to update short_term_plan.md: {e}")


async def _apply_completed_topics(
    user_id: str,
    module: str,
    completed_ids: list[str],
) -> None:
    """Mark topics as completed in the MongoDB learning plan."""
    if not completed_ids:
        return

    try:
        from bson import ObjectId
        from core.mongo_db import mongo_db_manager
        db = mongo_db_manager.get_database()

        prefix = f"modules.{module}"
        user = await asyncio.to_thread(
            db["users"].find_one,
            {"_id": ObjectId(user_id)},
            {f"{prefix}.learningPlan": 1},
        )
        if not user:
            return

        plan_dict = (user.get("modules") or {}).get(module, {}).get("learningPlan")
        if not plan_dict:
            return

        updated = False
        for week in plan_dict.get("weeks", []):
            for topic in week.get("topics", []):
                if topic.get("question_id") in completed_ids and topic.get("status") != "completed":
                    topic["status"] = "completed"
                    updated = True

            # Auto-update week status
            if updated:
                statuses = [t.get("status", "not_started") for t in week.get("topics", [])]
                if all(s == "completed" for s in statuses):
                    week["status"] = "completed"
                elif any(s in ("in_progress", "completed") for s in statuses):
                    week["status"] = "in_progress"

        if updated:
            await asyncio.to_thread(
                db["users"].update_one,
                {"_id": ObjectId(user_id)},
                {"$set": {f"{prefix}.learningPlan": plan_dict}},
            )
            logger.info(f"[Reflection] Marked {len(completed_ids)} topics complete for user={user_id}")

    except Exception as e:
        logger.error(f"[Reflection] Failed to update learning plan: {e}")
