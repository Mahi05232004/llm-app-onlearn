"""DS Tutor Agent factory — DeepAgent with skills-from-disk architecture.

Architecture:
  - Skills loaded from disk via CompositeBackend (no store seeding)
  - Per-session thread: {module}_{sessionId}
  - Memory: /AGENTS.md + /short_term_plan.md (auto-loaded)
  - Tools: get_lab_code, get_learn_code, execute_code, get_cross_mode_code,
           search_history, get/update_learning_plan, update_student_notes
  - Semantic RAG: per-user vector namespace for cross-session recall
"""

from __future__ import annotations
import logging
import pathlib
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.composite import CompositeBackend
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.store import StoreBackend
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from app.tutor.ds.prompts.system_prompts import BASE_SYSTEM_PROMPT
from app.tutor.core.tools.get_cross_mode_code import get_cross_mode_code
from app.tutor.core.tools.get_mode_code import get_lab_code, get_learn_code
from app.tutor.core.tools.execute_code import execute_code
from app.tutor.core.tools.search_history import search_history
from app.tutor.core.tools.learning_plan import get_learning_plan, update_learning_plan
from app.tutor.core.tools.student_notes import update_student_notes
from app.tutor.core.context_middleware import TutorContextMiddleware
from app.tutor.core.mode_tag_middleware import ModeTagMiddleware
from app.tutor.core.semantic_middleware import SemanticSummarizationMiddleware

# Minimal patch: force SkillsMiddleware to re-scan on each invocation
import app.tutor.core.patches  # noqa: F401

logger = logging.getLogger(__name__)

# Skills directory on disk (shared across DSA and DS agents)
_SKILLS_DIR = pathlib.Path(__file__).parent.parent / "core" / "skills"


def _make_backend(runtime):
    """Create a CompositeBackend that routes /skills/ to disk, everything else to store."""
    return CompositeBackend(
        default=StoreBackend(runtime),
        routes={
            "/skills/": FilesystemBackend(
                root_dir=str(_SKILLS_DIR),
                virtual_mode=True,
            ),
        },
    )


def create_ds_agent(
    *,
    model: BaseChatModel,
    store: BaseStore | None = None,
    checkpointer: Any = None,
    override_tools: list[Any] | None = None,
) -> CompiledStateGraph:
    """Create the DS tutor DeepAgent."""

    semantic_middleware = SemanticSummarizationMiddleware(
        model=model.with_config({"tags": ["summarizer"]}),
        backend=lambda runtime: runtime.store,
        trigger=("messages", 60),
        keep=("messages", 40),
        truncate_args_settings={
            "trigger": ("tokens", 80000),
            "keep": ("messages", 20),
            "max_length": 500,
        },
    )

    agent = create_deep_agent(
        model=model,
        system_prompt=BASE_SYSTEM_PROMPT,
        tools=override_tools if override_tools is not None else [
            get_lab_code,
            get_learn_code,
            execute_code,
            get_cross_mode_code,
            search_history,
            get_learning_plan,
            update_learning_plan,
            update_student_notes,
        ],
        skills=["/skills/"],
        memory=[
            "/AGENTS.md",
            "/short_term_plan.md",
            "/global_plan.md",  # Written by get_learning_plan/update_learning_plan — auto-loaded if present
        ],
        backend=_make_backend,
        store=store,
        checkpointer=checkpointer,
        middleware=[TutorContextMiddleware(), ModeTagMiddleware(), semantic_middleware],
    )
    return agent