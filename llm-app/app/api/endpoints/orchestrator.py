"""
Orchestrator API Endpoint.

This endpoint handles all chat interactions through the stateful handoff orchestrator.
Supports both regular (ainvoke) and streaming (astream_events) responses.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, AsyncGenerator
import logging
import json
import re

from app.supervisor.orchestrator import master_orchestrator
from app.supervisor.onboarding import onboarding_agent
from app.supervisor.onboarding_ds import onboarding_ds_agent

router = APIRouter()
logger = logging.getLogger(__name__)


def _serialise_messages(messages) -> list[dict[str, str]]:
    """Convert langchain BaseMessage list to simple role/content dicts for tracing."""
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
    result = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        elif isinstance(msg, SystemMessage):
            role = "system"
        elif isinstance(msg, ToolMessage):
            role = "tool"
        else:
            role = "unknown"
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        entry = {"role": role, "content": content[:2000]}  # cap per-message size
        if isinstance(msg, ToolMessage):
            entry["tool_call_id"] = getattr(msg, "tool_call_id", "")
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            entry["tool_calls"] = [
                {"name": tc.get("name", ""), "args": tc.get("args", {})} 
                for tc in msg.tool_calls
            ]
        result.append(entry)
    return result


class OrchestratorRequest(BaseModel):
    """Request model for orchestrator chat."""
    message: str
    sessionId: str = ""
    mode: str = "learn"  # 'learn' or 'code'
    threadId: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    is_onboarding: bool = False  # For onboarding mode, routes to Guide Agent
    user_id: Optional[str] = None  # User identifier for onboarding thread_id
    messages: Optional[list] = None  # Full conversation history for stateless mode
    files: Optional[Dict[str, Any]] = None  # Initial files to inject (e.g., student profile, plan)


class OrchestratorResponse(BaseModel):
    """Response model for orchestrator chat."""
    response: str
    threadId: str
    activeAgent: Optional[str] = None


@router.post("/", response_model=OrchestratorResponse)
async def chat_with_orchestrator(request: OrchestratorRequest):
    """
    Non-streaming chat with the Master Orchestrator.
    Use /chat-stream for streaming responses.
    """
    try:
        thread_id = request.threadId or f"orchestrator_{request.sessionId}"
        
        config = {"configurable": {"thread_id": thread_id}}
        
        inputs = {
            "messages": [("user", request.message)],
            "mode": request.mode,
            "files": {},
            "mode_changed": False,
            "user_id": request.user_id or "",
        }
        
        result = await master_orchestrator.ainvoke(inputs, config=config)
        
        messages = result.get("messages", [])
        if not messages:
            return OrchestratorResponse(
                response="I'm sorry, I couldn't process your request.",
                threadId=thread_id,
            )
        
        last_message = messages[-1]
        content = last_message.content
        
        if isinstance(content, list):
            text_blocks = [
                block.get("text", "") 
                for block in content 
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            final_response = "\n".join(text_blocks) or str(content)
        else:
            final_response = str(content)
        
        active_agent = None
        files = result.get("files", {})
        routing_data = files.get("/routing.json", {})
        if isinstance(routing_data, dict) and "content" in routing_data:
            try:
                routing = json.loads(routing_data["content"])
                active_agent = routing.get("active_agent")
            except:
                pass
        
        return OrchestratorResponse(
            response=final_response,
            threadId=thread_id,
            activeAgent=active_agent,
        )
        
    except Exception as e:
        logger.error(f"Error in orchestrator chat: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def chat_with_orchestrator_stream(request: OrchestratorRequest):
    """
    Streaming chat with the Master Orchestrator.
    Returns Server-Sent Events with token chunks.
    
    Event types:
    - token: Text content chunk
    - thinking: Reasoning/thought content
    - done: Final event with metadata (suggestions, activeAgent)
    - error: Error occurred
    """
    
    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Determine if this is an onboarding request
            if request.is_onboarding:
                # Route to standalone onboarding agent (flash model, own checkpoint)
                session_id = request.sessionId
                thread_id = f"onboarding_{session_id}"
                logger.info(f"[Onboarding Stream] Starting for session: {session_id}")
                
                config = {"configurable": {"thread_id": thread_id}}
                
                # Build onboarding message
                if request.message == '[START_ONBOARDING]':
                    message_text = "Hi, I'm new here and want to start learning!"
                else:
                    message_text = request.message
                
                inputs = {
                    "messages": [("user", message_text)],
                    "files": {},
                }
                
                # Pick the right onboarding agent based on module
                # DS sessions use ds_ prefix on their session IDs
                if session_id.startswith("ds_"):
                    agent_to_stream = onboarding_ds_agent
                    logger.info(f"[Onboarding Stream] Using DS onboarding agent")
                else:
                    agent_to_stream = onboarding_agent
            else:
                # Route to main orchestrator (pro model)
                thread_id = request.threadId or f"orchestrator_{request.sessionId}"
                logger.info(f"[Orchestrator Stream] Starting for session: {request.sessionId}, mode: {request.mode}")
                
                config = {"configurable": {"thread_id": thread_id}}
                
                # Regular chat: just use current message (checkpointer handles history)
                formatted_messages = [("user", request.message)]
                
                # Convert incoming files to StateBackend format (content as list of lines)
                def convert_files_format(files: Dict[str, Any]) -> Dict[str, Any]:
                    from datetime import datetime, UTC
                    converted = {}
                    for path, file_data in files.items():
                        content = file_data.get("content", "")
                        if isinstance(content, str):
                            lines = content.split("\n")
                            now = datetime.now(UTC).isoformat()
                            converted[path] = {
                                "content": lines,
                                "created_at": now,
                                "modified_at": now,
                                "metadata": file_data.get("metadata", {})
                            }
                        else:
                            converted[path] = file_data
                    return converted
                
                files_input = convert_files_format(request.files) if request.files else {}
                
                inputs = {
                    "messages": formatted_messages,
                    "mode": request.mode,
                    "files": files_input,
                    "mode_changed": False,
                    "user_id": request.user_id or "",
                    "session_id": request.sessionId or "",
                }
                
                agent_to_stream = master_orchestrator
            
            full_response = ""
            active_agent = None
            output_files = {}       # captured from final on_chain_end
            tool_events = []        # captured tool calls for trace
            # Track when a delegation/handoff tool fires so we can stop
            # accumulating text tokens from the agent's *second* internal
            # LLM call (the one that runs after the tool result returns).
            delegation_seen = False
            
            # Stream events from the selected agent
            async for event in agent_to_stream.astream_events(inputs, config=config, version="v2"):
                kind = event.get("event")
                
                # Stream tokens from chat model (all agents including master)
                if kind == "on_chat_model_stream":
                    # After a delegation tool has fired, the react agent calls
                    # the LLM again with the tool result.  That second response
                    # is the "duplicate greeting" — suppress it.
                    if delegation_seen:
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
                            full_response += text_to_yield
                            yield f"data: {json.dumps({'type': 'token', 'content': text_to_yield})}\n\n"

                # Stream tool start events to frontend
                elif kind == "on_tool_start":
                    tool_name = event.get("name", "")
                    # Skip internal/framework tools that aren't useful to show
                    if tool_name and tool_name not in ("__interrupt",):
                        tool_input = event.get("data", {}).get("input", {})
                        # Truncate input for display
                        input_preview = str(tool_input)[:300] if tool_input else ""
                        yield f"data: {json.dumps({'type': 'tool_start', 'name': tool_name, 'input': input_preview})}\n\n"

                # Stream tool end events + capture for tracing
                elif kind == "on_tool_end":
                    data = event.get("data", {})
                    tool_name = event.get("name", "")
                    raw_output = data.get("output", "")
                    tool_output_str = ""
                    if isinstance(raw_output, str):
                        tool_output_str = raw_output[:500]
                    elif hasattr(raw_output, "content"):
                        tool_output_str = str(raw_output.content)[:500]
                    tool_events.append({"tool": tool_name, "output_preview": tool_output_str})
                    
                    # Mark delegation so we suppress subsequent LLM tokens
                    if tool_name in ("delegate_to_agent", "hand_back_to_master"):
                        delegation_seen = True
                    
                    # Stream to frontend
                    if tool_name and tool_name not in ("__interrupt",):
                        yield f"data: {json.dumps({'type': 'tool_end', 'name': tool_name, 'output': tool_output_str[:200]})}\n\n"
                
                # Detect onboarding completion from tool output
                elif request.is_onboarding and kind in ("on_tool_end", "on_chain_end"):
                    # Try multiple paths where tool output might appear
                    data = event.get("data", {})
                    
                    # on_tool_end: output could be str, ToolMessage, or dict
                    candidates = []
                    raw_output = data.get("output", "")
                    if isinstance(raw_output, str):
                        candidates.append(raw_output)
                    elif hasattr(raw_output, "content"):
                        # ToolMessage or AIMessage - content is the string
                        content = raw_output.content
                        if isinstance(content, str):
                            candidates.append(content)
                    
                    # on_chain_end: check if output dict has messages with tool results
                    if isinstance(raw_output, dict):
                        msgs = raw_output.get("messages", [])
                        if isinstance(msgs, list):
                            for msg in msgs:
                                if hasattr(msg, "content") and isinstance(msg.content, str):
                                    candidates.append(msg.content)
                    
                    # Also check if data itself has messages (some event formats)
                    if isinstance(data, dict) and "messages" in data:
                        msgs = data.get("messages", [])
                        if isinstance(msgs, list):
                            for msg in msgs:
                                if hasattr(msg, "content") and isinstance(msg.content, str):
                                    candidates.append(msg.content)
                    
                    for candidate in candidates:
                        if "onboarding_complete" in candidate:
                            try:
                                tool_data = json.loads(candidate)
                                if tool_data.get("status") == "onboarding_complete":
                                    onboarding_data = {
                                        "type": "onboarding_complete",
                                        "student_profile": tool_data.get("student_profile"),
                                    }
                                    yield f"data: {json.dumps(onboarding_data)}\n\n"
                                    # Terminate stream immediately upon completion
                                    return
                            except (json.JSONDecodeError, TypeError):
                                pass

                # Capture final state for routing info (main orchestrator graph)
                elif kind == "on_chain_end":
                    output = event.get("data", {}).get("output", {})
                    if isinstance(output, dict) and "files" in output:
                        output_files = output.get("files", {})
                        routing_data = output_files.get("/routing.json", {})
                        if isinstance(routing_data, dict) and "content" in routing_data:
                            try:
                                routing = json.loads(routing_data["content"])
                                active_agent = routing.get("active_agent")
                            except:
                                pass
            
            # Parse suggestions from final response
            suggestions = []
            suggestions_match = re.search(r'<suggestions>(.*?)</suggestions>', full_response, re.DOTALL)
            if suggestions_match:
                suggestions_raw = suggestions_match.group(1).strip()
                suggestions = [s.strip() for s in suggestions_raw.split('|') if s.strip()]
            
            # Parse action buttons from final response
            actions = []
            actions_match = re.search(r'<actions>(.*?)</actions>', full_response, re.DOTALL)
            if actions_match:
                actions_raw = actions_match.group(1).strip()
                actions = [a.strip() for a in actions_raw.split('|') if a.strip()]
            
            # Send final event with metadata
            yield f"data: {json.dumps({'type': 'done', 'threadId': thread_id, 'activeAgent': active_agent, 'suggestions': suggestions, 'actions': actions})}\n\n"
            
            # ── Record full turn trace (fire-and-forget) ──
            try:
                import os
                if os.environ.get("ENABLE_TEST_ENDPOINTS", "0") == "1":
                    import time
                    from tests.supervisor.tracing.tracer import turn_tracer
                    
                    # Collect tool names from captured events
                    tools_called = list({ev["tool"] for ev in tool_events if ev.get("tool")})
                    
                    # Capture message history from checkpointer state
                    message_history = []
                    try:
                        state_snapshot = await agent_to_stream.aget_state(config)
                        all_messages = state_snapshot.values.get("messages", [])
                        # Exclude the last message (current turn's response)
                        # to get the history *before* this turn's output
                        if all_messages:
                            message_history = _serialise_messages(all_messages)
                    except Exception as hist_err:
                        logger.debug(f"Could not capture message history: {hist_err}")
                    
                    turn_tracer.record_turn(
                        session_id=request.sessionId,
                        user_id=request.user_id or "",
                        input_message=request.message,
                        input_files=files_input if not request.is_onboarding else {},
                        output_response=full_response,
                        output_files=output_files,
                        agent_name=active_agent or "",
                        tools_called=tools_called,
                        tool_events=tool_events,
                        message_history=message_history,
                        iteration=0,
                        thread_id=thread_id,
                        mode=request.mode,
                    )
            except Exception as trace_err:
                logger.debug(f"Turn tracing failed (non-critical): {trace_err}")
            
            logger.info(f"[Orchestrator Stream] Completed for session: {request.sessionId}")
            
        except Exception as e:
            logger.error(f"[Orchestrator Stream] Error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
