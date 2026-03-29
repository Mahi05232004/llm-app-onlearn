"""ModeTagMiddleware — prepends [LEARN] or [CODE] to AI responses.

This middleware intercepts the model response inline (via awrap_model_call)
and prepends a mode tag to the AIMessage content. The tag is baked into the
checkpointed message so the agent sees it on future turns, but it never
reaches the frontend database (Next.js saves the raw streamed tokens).

Usage:
    agent = create_deep_agent(
        ...,
        middleware=[ModeTagMiddleware(), ...],
    )

    # Pass mode via config.configurable.tutor_context:
    config = {"configurable": {"tutor_context": {"mode": "learn", ...}}}
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)


class ModeTagMiddleware(AgentMiddleware):
    """Prepends [LEARN] or [CODE] to AI responses in the checkpoint.

    Reads `mode` from `config.configurable.tutor_context.mode` (same source
    as TutorContextMiddleware) and tags the AIMessage content after generation.
    """

    def _get_mode(self) -> str | None:
        """Read the active mode from LangGraph config."""
        try:
            from langgraph.config import get_config
            lc_config = get_config()
            ctx = lc_config.get("configurable", {}).get("tutor_context")
            if ctx:
                return ctx.get("mode")
        except Exception:
            pass
        return None

    def _tag_ai_message(self, msg: AIMessage, mode: str) -> AIMessage:
        """Prepend [MODE] tag to the AIMessage content."""
        import re
        
        tag = f"[{mode.upper()}] "
        # Regex to match any leading tags like [LEARN], [CODE] with optional spaces
        tag_pattern = re.compile(r"^(?:\s*\[(?:LEARN|CODE|learn|code)\]\s*)+", re.IGNORECASE)

        if isinstance(msg.content, str):
            clean_content = tag_pattern.sub("", msg.content)
            msg.content = tag + clean_content
        elif isinstance(msg.content, list):
            # Content is a list of blocks (e.g. [{"type": "text", "text": "..."}])
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    clean_content = tag_pattern.sub("", block["text"])
                    block["text"] = tag + clean_content
                    break
        return msg

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Sync: tag the AI response with the active mode."""
        response = handler(request)
        mode = self._get_mode()
        if not mode:
            return response

        if response.result:
            last_msg = response.result[-1]
            if isinstance(last_msg, AIMessage) and not getattr(last_msg, "tool_calls", None):
                self._tag_ai_message(last_msg, mode)
                logger.debug("[ModeTagMiddleware] Tagged AI message with [%s]", mode.upper())

        return response

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Async: tag the AI response with the active mode."""
        response = await handler(request)
        mode = self._get_mode()
        if not mode:
            return response

        if response.result:
            last_msg = response.result[-1]
            if isinstance(last_msg, AIMessage) and not getattr(last_msg, "tool_calls", None):
                self._tag_ai_message(last_msg, mode)
                logger.debug("[ModeTagMiddleware] Tagged AI message with [%s]", mode.upper())

        return response
