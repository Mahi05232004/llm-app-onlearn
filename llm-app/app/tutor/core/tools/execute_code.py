"""execute_code tool — Run student code via Judge0 and return the result.

Used exclusively by the Lab Mentor skill to internally run code and
guide the student based on actual output, errors, and test case results.
"""
import os
import base64
import logging
from typing import Optional, Dict, Any

import httpx
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Judge0 server URL — internal Docker network (set JUDGE0_URL env var to override)
JUDGE0_URL = os.getenv("JUDGE0_URL", "http://judge0-server:2358").rstrip('/')

# Judge0 language ID mapping
LANGUAGE_MAP = {
    "python": 71,
    "cpp": 54,
    "c": 50,
    "java": 62,
    "go": 60,
    "rust": 73,
    "javascript": 63,
}


def _encode_b64(text: str) -> str:
    if not text:
        return ""
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")


def _decode_b64(encoded: Optional[str]) -> str:
    if not encoded:
        return ""
    try:
        return base64.b64decode(encoded).decode("utf-8")
    except Exception:
        return ""


@tool("execute_code")
async def execute_code(
    code: str,
    language: str,
    stdin: Optional[str] = "",
    time_limit: Optional[float] = 5.0,
    memory_limit: Optional[int] = 262144,
) -> Dict[str, Any]:
    """Execute the student's code with given input and return the result.

    Use this tool to:
    - Run the student's current lab code to see what it actually does.
    - Test with specific inputs that expose bugs.
    - Verify a proposed fix works before suggesting it.

    IMPORTANT: Only use this in Code mode ([CODE] tag). Do not run learn-mode
    scratchpad code — use this exclusively for the lab editor code.

    Args:
        code: The code to execute (copy from the student's lab editor or get_lab_code).
        language: Programming language ('python', 'cpp', 'java', 'go', 'rust', 'javascript').
        stdin: Standard input to feed the program (e.g. "5\\n1 2 3 4 5" for n=5, then array).
        time_limit: Execution time limit in seconds (default 5.0).
        memory_limit: Memory limit in KB (default 262144 = 256MB).

    Returns:
        Dict with stdout, stderr, compile_output, status, time, memory.
    """
    language_id = LANGUAGE_MAP.get(language.lower())
    if not language_id:
        supported = ", ".join(LANGUAGE_MAP.keys())
        return {
            "error": f"Unsupported language: '{language}'. Supported: {supported}",
            "status": "Error",
        }

    payload = {
        "source_code": _encode_b64(code),
        "language_id": language_id,
        "stdin": _encode_b64(stdin or ""),
        "cpu_time_limit": time_limit,
        "memory_limit": memory_limit,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{JUDGE0_URL}/submissions",
                json=payload,
                params={"base64_encoded": "true", "wait": "true"},
            )
            if response.status_code not in (200, 201):
                return {
                    "error": f"Judge0 returned HTTP {response.status_code}: {response.text}",
                    "status": "Error",
                }
            result = response.json()

    except httpx.TimeoutException:
        return {"error": "Code execution timed out (Judge0 did not respond).", "status": "Timeout"}
    except httpx.RequestError as exc:
        return {
            "error": (
                f"Could not connect to code execution service: {exc}. "
                "Judge0 may not be running in this environment."
            ),
            "status": "Unavailable",
        }

    status_info = result.get("status", {})
    return {
        "stdout": _decode_b64(result.get("stdout")),
        "stderr": _decode_b64(result.get("stderr")),
        "compile_output": _decode_b64(result.get("compile_output")),
        "status": status_info.get("description", "Unknown"),
        "status_id": status_info.get("id", 0),
        "time": result.get("time"),
        "memory": result.get("memory"),
        "exit_code": result.get("exit_code"),
    }
