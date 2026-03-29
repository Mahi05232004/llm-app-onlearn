"""
Code Execution API using Judge0.

This module provides endpoints for executing code in various programming languages
using the Judge0 code execution engine.
"""

import base64
import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# Judge0 server URL - internal Docker network
JUDGE0_URL = os.getenv("JUDGE0_URL", "http://judge0-server:2358").rstrip('/')

# Language ID mapping for Judge0
# Full list: https://github.com/judge0/judge0/blob/master/docs/api/languages.md
LANGUAGE_MAP = {
    "python": 71,      # Python 3
    "cpp": 54,         # C++ (GCC 9.2.0)
    "c": 50,           # C (GCC 9.2.0)
    "java": 62,        # Java (OpenJDK 13.0.1)
    "go": 60,          # Go (1.13.5)
    "rust": 73,        # Rust (1.40.0)
}


class ExecutionRequest(BaseModel):
    """Request body for code execution."""
    code: str
    language: str
    stdin: Optional[str] = ""
    time_limit: Optional[float] = 5.0  # seconds
    memory_limit: Optional[int] = 262144  # KB (256 MB)


class ExecutionResponse(BaseModel):
    """Response from code execution."""
    stdout: str
    stderr: str
    compile_output: str
    status: str
    status_id: int
    time: Optional[str]
    memory: Optional[int]
    exit_code: Optional[int]


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


@router.post("/execute", response_model=ExecutionResponse)
async def execute_code(request: ExecutionRequest):
    """
    Execute code using Judge0.
    
    Args:
        request: ExecutionRequest containing code, language, and optional stdin
        
    Returns:
        ExecutionResponse with stdout, stderr, status, and execution metrics
    """
    # Validate language
    language_id = LANGUAGE_MAP.get(request.language.lower())
    if not language_id:
        supported = ", ".join(LANGUAGE_MAP.keys())
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language: {request.language}. Supported: {supported}"
        )
    
    # Prepare submission payload for Judge0
    submission = {
        "source_code": encode_base64(request.code),
        "language_id": language_id,
        "stdin": encode_base64(request.stdin or ""),
        "cpu_time_limit": request.time_limit,
        "memory_limit": request.memory_limit,
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Submit code and wait for result (synchronous mode)
            response = await client.post(
                f"{JUDGE0_URL}/submissions",
                json=submission,
                params={
                    "base64_encoded": "true",
                    "wait": "true"  # Synchronous execution
                }
            )
            
            if response.status_code != 200 and response.status_code != 201:
                raise HTTPException(
                    status_code=502,
                    detail=f"Judge0 error: {response.text}"
                )
            
            result = response.json()
            
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Code execution timed out"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to connect to Judge0: {str(e)}"
        )
    
    # Extract and decode results
    status_info = result.get("status", {})
    
    return ExecutionResponse(
        stdout=decode_base64(result.get("stdout")),
        stderr=decode_base64(result.get("stderr")),
        compile_output=decode_base64(result.get("compile_output")),
        status=status_info.get("description", "Unknown"),
        status_id=status_info.get("id", 0),
        time=result.get("time"),
        memory=result.get("memory"),
        exit_code=result.get("exit_code")
    )


@router.get("/languages")
async def get_supported_languages():
    """
    Get list of supported programming languages.
    
    Returns:
        Dictionary mapping language names to their Judge0 IDs
    """
    return {
        "languages": [
            {"name": "Python", "value": "python", "judge0_id": 71},
            {"name": "C++", "value": "cpp", "judge0_id": 54},
            {"name": "C", "value": "c", "judge0_id": 50},
            {"name": "Java", "value": "java", "judge0_id": 62},
            {"name": "Go", "value": "go", "judge0_id": 60},
            {"name": "Rust", "value": "rust", "judge0_id": 73},
        ]
    }


@router.get("/health")
async def judge0_health_check():
    """
    Check if Judge0 service is available.
    
    Returns:
        Health status of Judge0 connection
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{JUDGE0_URL}/about")
            if response.status_code == 200:
                return {
                    "status": "healthy",
                    "judge0_version": response.json().get("version", "unknown")
                }
            else:
                return {"status": "unhealthy", "error": "Unexpected response"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
