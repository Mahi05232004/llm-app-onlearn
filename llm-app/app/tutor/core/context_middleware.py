"""TutorContextMiddleware — injects per-turn context into the system prompt.

Slim version: only injects essential context that the agent always needs.
Code, solution approaches, and history retrieval are handled by the
Context Agent subagent on demand.

Context injected:
  - Current time + time gap since last interaction
  - Active module (DSA / Data Science)
  - Session identity (question title, interface mode)
  - Question context (problem statement + concepts — no solution approaches)
  - Mode UI description (Learn / Code interface layout)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Annotated, Any, NotRequired, TypedDict

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
    PrivateStateAttr,
)

from deepagents.middleware._utils import append_to_system_message

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# INTERFACE DESCRIPTIONS — static, included based on active mode
# ═══════════════════════════════════════════════════════════════════════════════

_LEARN_UI = """\
# Interface: Learn Mode

## Visual Layout
- **Left Panel**: Mission Briefing (Problem Statement, Examples, Constraints).
- **Center Panel**: **Main Chat Interface**. This is where the primary conversation happens.
- **Right Panel**: A secondary Code Editor (for quick snippets, not full execution).

## Your Role in this UI
The student is focused on **discussion and concept building**.
- Utilize the large chat area for detailed explanations (but keep them concise).
- The code editor is available, but the user is likely not running full test cases here.
- Focus on clarifying the "What" and "Why" before moving to the Code Mode.
- Drawing ASCII diagrams or step-by-step traces works well here.
"""

_CODE_UI = """\
# Interface: Code Mode

## Visual Layout
- **Left Panel**: Mission Briefing.
- **Center Panel**: **Full Code Editor** (Monaco-style) with "Run" and "Check" buttons.
- **Bottom Panel**: Test Cases (Input/Output).
- **Right Panel**: **Lab Assistant Chat**. This is where you live — a narrower side column.

## Your Role in this UI
- You are a **Side Assistant**. The user's focus is on the Code Editor (Center).
- Your messages appear in the narrower right-hand side panel.
- Keep responses short and punchy; they shouldn't clutter the coding view.
- **Direct them to the Editor**: "In your `reverse_array` function..."
- **Encourage Testing**: "Hit the Run button to see..."
- **Debug actively**: Look at their code in the center and the test results at the bottom.
- **CRITICAL**: You CANNOT edit the code for them. You must guide them to type the fix themselves.
"""

_INTERFACE_SECTIONS = {
    "learn": _LEARN_UI,
    "code": _CODE_UI,
}

_MODULE_NAMES = {
    "dsa": "Data Structures & Algorithms (DSA)",
    "ds": "Data Science & Machine Learning",
}


# ═══════════════════════════════════════════════════════════════════════════════
# STATE SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

class TutorContextState(AgentState):
    """State schema for TutorContextMiddleware."""
    tutor_context: NotRequired[Annotated[dict[str, Any], PrivateStateAttr]]


class TutorContextStateUpdate(TypedDict):
    """State update for TutorContextMiddleware."""
    tutor_context: dict[str, Any]


# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXT FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════════

def _format_time_section(last_interaction_at: Any = None) -> str:
    """Format current time and time since last interaction."""
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST)

    time_gap_note = ""
    if last_interaction_at:
        if last_interaction_at.tzinfo is None:
            last_interaction_at = last_interaction_at.replace(tzinfo=timezone.utc)
        diff = datetime.now(timezone.utc) - last_interaction_at
        total_hours = diff.total_seconds() / 3600
        if total_hours > 24:
            time_gap_note = f"\n- Last interaction: {int(total_hours // 24)} days ago"
        elif total_hours > 1:
            time_gap_note = f"\n- Last interaction: {int(total_hours)} hours ago"

    return (
        "# Current Time\n"
        f"- Date & Time: {now.strftime('%A, %B %d, %Y at %I:%M %p IST')}"
        f"{time_gap_note}\n"
    )


def _format_question_context(question_data: dict) -> str:
    """Format question data into a context section.

    Limited to: title, difficulty, type, question ID, topic, concepts,
    and problem statement. Solution approaches are handled by the
    Context Agent's get_solution_approaches tool.
    """
    parts = ["# Current Question Context\n"]

    title = question_data.get("question_title", "Unknown")
    difficulty = question_data.get("difficulty", "")
    q_type = question_data.get("question_type", "")
    has_code = question_data.get("has_code", False)
    question_id = question_data.get("question_id", "")

    parts.append(f"**Title:** {title}")
    if question_id:
        parts.append(f"**Question ID:** {question_id}")
    if difficulty:
        parts.append(f"**Difficulty:** {difficulty}")
    if q_type:
        parts.append(f"**Type:** {q_type}")
    parts.append(f"**Has Code:** {'Yes' if has_code else 'No'}")

    step_title = question_data.get("step_title", "")
    sub_step_title = question_data.get("sub_step_title", "")
    if step_title:
        parts.append(f"**Topic:** {step_title}")
    if sub_step_title:
        parts.append(f"**Subtopic:** {sub_step_title}")

    concepts = question_data.get("concepts") or question_data.get("standard_concepts") or []
    if concepts:
        parts.append(f"**Key Concepts:** {', '.join(concepts)}")

    question_text = question_data.get("question", "")
    if question_text:
        parts.append(f"\n## Problem Statement\n{question_text}")

    system_instructions = question_data.get("system_instructions", "")
    if system_instructions:
        parts.append(f"\n## Special Instructions\n{system_instructions}")

    return "\n".join(parts)


def format_tutor_context(ctx: dict[str, Any]) -> str:
    """Format the tutor_context dict into a system prompt section.

    Injects only essential context:
    - Time + time gap
    - Active module
    - Session identity
    - Question context (problem + concepts, no approaches)
    - Mode UI description
    """
    mode = ctx.get("mode", "learn")
    module = ctx.get("module", "dsa")
    question_data = ctx.get("question_data")
    last_interaction_at = ctx.get("last_interaction_at")

    # 1. Time section
    time_section = _format_time_section(last_interaction_at)

    # 2. Module section
    module_name = _MODULE_NAMES.get(module, module.upper())
    module_section = (
        "# Active Module\n"
        f"- **Module**: {module_name}\n"
        "- Tailor all explanations, analogies, and examples to this domain.\n"
    )

    # 3. Session identity
    session_section = "# Active Session\n"
    if question_data:
        q_title = question_data.get("question_title", "Unknown")
        session_section += f"- **Current Question**: {q_title}\n"
    session_section += f"- **Interface**: {mode.upper()}\n"

    # 4. Interface section
    interface_section = _INTERFACE_SECTIONS.get(mode, _LEARN_UI)

    # 5. Question context (limited — no solution approaches)
    question_section = ""
    if question_data:
        question_section = "\n\n" + _format_question_context(question_data)

    return (
        f"{time_section}\n{module_section}\n{session_section}\n"
        f"{interface_section}{question_section}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════════════════

class TutorContextMiddleware(AgentMiddleware):
    """Injects per-turn tutor context into the system prompt.

    Reads tutor_context from config.configurable (bypasses PrivateStateAttr)
    and formats essential context into the system prompt.
    """

    state_schema = TutorContextState

    def modify_request(self, request: ModelRequest) -> ModelRequest:
        """Inject tutor context into the system message."""
        ctx = None
        try:
            from langgraph.config import get_config
            lc_config = get_config()
            ctx = lc_config.get("configurable", {}).get("tutor_context")
        except Exception:
            pass

        if not ctx:
            ctx = request.state.get("tutor_context")

        if not ctx:
            logger.debug("[TutorContextMiddleware] No tutor_context found")
            return request

        context_str = format_tutor_context(ctx)
        new_system_message = append_to_system_message(
            request.system_message, f"\n<tutor_context>\n{context_str}\n</tutor_context>"
        )
        return request.override(system_message=new_system_message)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Sync wrapper."""
        modified_request = self.modify_request(request)
        return handler(modified_request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Async wrapper."""
        modified_request = self.modify_request(request)
        return await handler(modified_request)
