"""
Code Execution Tool.

Provides code execution capability via Judge0 for both lab mentor and code reviewer agents.
"""
import os
import base64
import logging
from typing import Optional, Dict, Any

import httpx
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Judge0 server URL - internal Docker network
JUDGE0_URL = os.getenv("JUDGE0_URL", "http://judge0-server:2358")

# Language ID mapping for Judge0
LANGUAGE_MAP = {
    "python": 71,
    "cpp": 54,
    "c": 50,
    "java": 62,
    "go": 60,
    "rust": 73,
}


def encode_base64(text: str) -> str:
    """Encode text to base64."""
    if not text:
        return ""
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")


def decode_base64(encoded: Optional[str]) -> str:
    """Decode base64 to text, handling None values."""
    if not encoded:
        return ""
    try:
        return base64.b64decode(encoded).decode("utf-8")
    except Exception:
        return ""


@tool("execute_code")
async def execute_code_tool(
    code: str,
    language: str,
    stdin: Optional[str] = "",
    time_limit: Optional[float] = 5.0,
    memory_limit: Optional[int] = 262144,
) -> Dict[str, Any]:
    """
    Execute code with specific inputs to test student solutions.
    
    Use this tool to:
    - Generate failing test cases that expose bugs
    - Verify that a fix works correctly
    - Demonstrate step-by-step execution with specific input
    
    Args:
        code: The code to execute (student's current code or modified version)
        language: Programming language (python, cpp, c, java, go, rust)
        stdin: Input to provide via stdin (e.g., "5\\n1 2 3 4 5" for n=5 and array)
        time_limit: Execution time limit in seconds (default: 5.0)
        memory_limit: Memory limit in KB (default: 262144 / 256MB)
    
    Returns:
        Dict containing:
        - stdout: Program output
        - stderr: Error output  
        - compile_output: Compilation errors if any
        - status: Execution status (Accepted, Wrong Answer, Time Limit Exceeded, etc.)
        - time: Execution time
        - memory: Memory used in KB
    """
    # Validate language
    language_id = LANGUAGE_MAP.get(language.lower())
    if not language_id:
        supported = ", ".join(LANGUAGE_MAP.keys())
        return {
            "error": f"Unsupported language: {language}. Supported: {supported}",
            "status": "Error"
        }
    
    # Prepare submission payload for Judge0
    submission = {
        "source_code": encode_base64(code),
        "language_id": language_id,
        "stdin": encode_base64(stdin or ""),
        "cpu_time_limit": time_limit,
        "memory_limit": memory_limit,
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{JUDGE0_URL}/submissions",
                json=submission,
                params={
                    "base64_encoded": "true",
                    "wait": "true"
                }
            )
            
            if response.status_code not in (200, 201):
                return {
                    "error": f"Judge0 error: {response.text}",
                    "status": "Error"
                }
            
            result = response.json()
            
    except httpx.TimeoutException:
        return {
            "error": "Code execution timed out",
            "status": "Timeout"
        }
    except httpx.RequestError as e:
        return {
            "error": f"Failed to connect to Judge0: {str(e)}",
            "status": "Error"
        }
    
    # Extract and decode results
    status_info = result.get("status", {})
    
    return {
        "stdout": decode_base64(result.get("stdout")),
        "stderr": decode_base64(result.get("stderr")),
        "compile_output": decode_base64(result.get("compile_output")),
        "status": status_info.get("description", "Unknown"),
        "status_id": status_info.get("id", 0),
        "time": result.get("time"),
        "memory": result.get("memory"),
        "exit_code": result.get("exit_code")
    }


__all__ = ["execute_code_tool"]
