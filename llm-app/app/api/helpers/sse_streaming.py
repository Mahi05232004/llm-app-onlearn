"""SSE streaming helpers — unified event generator and response parser.

Extracted from orchestrator.py to eliminate streaming code duplication
between the onboarding and tutor paths.
"""

import json
import re
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


async def stream_agent_events(
    agent,
    inputs: dict,
    config: dict,
    *,
    accumulator: dict | None = None,
) -> AsyncGenerator[str, None]:
    """Unified SSE event generator for any LangGraph agent.

    Yields SSE-formatted strings for:
    - token: text content chunks
    - thinking: reasoning/thought content
    - tool_start / tool_end: tool execution events

    Args:
        agent: Compiled LangGraph agent.
        inputs: Agent input dict (messages, tutor_context, etc.).
        config: LangGraph config with thread_id etc.
        accumulator: Optional mutable dict to collect side-effects:
            - "full_response": str (accumulated text)
            - "tool_events": list[dict] (tool name + output preview)
            - "output_files": dict (captured from chain_end events)
            - "scratchpad_updated": bool (whether short_term_plan.md was touched)
    """
    if accumulator is None:
        accumulator = {}

    accumulator.setdefault("full_response", "")
    accumulator.setdefault("tool_events", [])
    accumulator.setdefault("output_files", {})
    accumulator.setdefault("scratchpad_updated", False)

    async for event in agent.astream_events(inputs, config=config, version="v2"):
        kind = event.get("event")

        # ── Stream tokens ──
        if kind == "on_chat_model_stream":
            tags = event.get("tags", [])
            if "summarizer" in tags:
                continue

            data = event.get("data", {})
            chunk = data.get("chunk")

            if chunk and hasattr(chunk, "content"):
                content = chunk.content
                text_to_yield = ""

                if isinstance(content, str):
                    text_to_yield = content
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, str):
                            text_to_yield += part
                        elif isinstance(part, dict):
                            part_type = part.get("type")
                            if part_type == "text":
                                text_to_yield += part.get("text", "")
                            elif part_type in ("thought", "thinking"):
                                thought_content = (
                                    part.get("text", "") or
                                    part.get("thought", "") or
                                    part.get("thinking", "")
                                )
                                if thought_content:
                                    yield f"data: {json.dumps({'type': 'thinking', 'content': thought_content})}\n\n"

                if text_to_yield:
                    accumulator.setdefault("in_think_block", False)
                    buffer = accumulator.setdefault("think_buffer", "") + text_to_yield
                    
                    while buffer:
                        if not accumulator["in_think_block"]:
                            if "<think>" in buffer:
                                before, after = buffer.split("<think>", 1)
                                if before:
                                    accumulator["full_response"] += before
                                    yield f"data: {json.dumps({'type': 'token', 'content': before})}\n\n"
                                accumulator["in_think_block"] = True
                                buffer = after
                            else:
                                # Check if buffer ends with a prefix of "<think>"
                                maybe_think = False
                                for i in range(1, len("<think>")):
                                    if buffer.endswith("<think>"[:i]):
                                        maybe_think = True
                                        accumulator["think_buffer"] = buffer[-i:]
                                        buffer = buffer[:-i]
                                        break
                                if not maybe_think:
                                    accumulator["think_buffer"] = ""
                                if buffer:
                                    accumulator["full_response"] += buffer
                                    yield f"data: {json.dumps({'type': 'token', 'content': buffer})}\n\n"
                                break
                        else:
                            if "</think>" in buffer:
                                before, after = buffer.split("</think>", 1)
                                if before:
                                    yield f"data: {json.dumps({'type': 'thinking', 'content': before})}\n\n"
                                accumulator["in_think_block"] = False
                                buffer = after
                            else:
                                # Check if buffer ends with a prefix of "</think>"
                                maybe_think = False
                                for i in range(1, len("</think>")):
                                    if buffer.endswith("</think>"[:i]):
                                        maybe_think = True
                                        accumulator["think_buffer"] = buffer[-i:]
                                        buffer = buffer[:-i]
                                        break
                                if not maybe_think:
                                    accumulator["think_buffer"] = ""
                                if buffer:
                                    yield f"data: {json.dumps({'type': 'thinking', 'content': buffer})}\n\n"
                                break

                if hasattr(chunk, "additional_kwargs"):
                    reasoning = chunk.additional_kwargs.get("reasoning_content", "")
                    if reasoning:
                        yield f"data: {json.dumps({'type': 'thinking', 'content': reasoning})}\n\n"

                # Check for streaming tool call chunks (args deltas)
                if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
                    for tc in chunk.tool_call_chunks:
                        if tc.get("args") or tc.get("name"):
                            yield f"data: {json.dumps({'type': 'tool_chunk', 'name': tc.get('name') or '', 'input': tc.get('args') or ''})}\n\n"

        # ── Tool events ──
        elif kind == "on_tool_start":
            tool_name = event.get("name", "")
            if tool_name and tool_name not in ("__interrupt",):
                tool_input = event.get("data", {}).get("input", {})
                input_preview = str(tool_input)[:300] if tool_input else ""
                yield f"data: {json.dumps({'type': 'tool_start', 'name': tool_name, 'input': input_preview})}\n\n"

                if tool_name in ("edit_file", "write_file"):
                    target_file = tool_input.get("file") or tool_input.get("path") or ""
                    if "short_term_plan.md" in target_file:
                        accumulator["scratchpad_updated"] = True

        elif kind == "on_tool_end":
            data = event.get("data", {})
            tool_name = event.get("name", "")
            raw_output = data.get("output", "")
            tool_output_str = ""
            if isinstance(raw_output, str):
                tool_output_str = raw_output[:500]
            elif hasattr(raw_output, "content"):
                tool_output_str = str(raw_output.content)[:500]
            accumulator["tool_events"].append({"tool": tool_name, "output_preview": tool_output_str})

            if tool_name and tool_name not in ("__interrupt",):
                yield f"data: {json.dumps({'type': 'tool_end', 'name': tool_name, 'output': tool_output_str[:200]})}\n\n"

        # ── Capture output files ──
        elif kind == "on_chain_end":
            output = event.get("data", {}).get("output", {})
            if isinstance(output, dict) and "files" in output:
                accumulator["output_files"] = output.get("files", {})


def parse_agent_response(full_response: str) -> dict:
    """Extract suggestions, actions, and next_question_id from agent response.

    The agent is instructed to emit these in XML-like tags:
        <suggestions>Action 1|Action 2|Action 3</suggestions>
        <actions>go_to_code|im_done|next_question</actions>
        <next_question>q_1_2_3</next_question>

    Returns:
        dict with keys: suggestions (list[str]), actions (list[str]),
        next_question_id (str|None)
    """
    suggestions = []
    suggestions_match = re.search(r'<suggestions>(.*?)</suggestions>', full_response, re.DOTALL)
    if suggestions_match:
        suggestions_raw = suggestions_match.group(1).strip()
        suggestions = [s.strip() for s in suggestions_raw.split('|') if s.strip()]

    actions = []
    actions_match = re.search(r'<actions>(.*?)</actions>', full_response, re.DOTALL)
    if actions_match:
        actions_raw = actions_match.group(1).strip()
        actions = [a.strip() for a in actions_raw.split('|') if a.strip()]

    next_question_id = None
    nq_match = re.search(r'<next_question>(.*?)</next_question>', full_response, re.DOTALL)
    if nq_match:
        next_question_id = nq_match.group(1).strip()

    return {
        "suggestions": suggestions,
        "actions": actions,
        "next_question_id": next_question_id,
    }
