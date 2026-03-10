"""
Test Case Validation API.

This module provides endpoints for validating user code against test cases
using Judge0 code execution engine.
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from api.execution import execute_code, ExecutionRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


class TestCase(BaseModel):
    """A single test case."""
    input: str
    expected_output: str
    is_sample: bool = True


class ValidationRequest(BaseModel):
    """Request body for code validation."""
    code: str
    language: str
    boilerplate_full: str
    test_cases: List[TestCase]
    time_limit: Optional[float] = 2.0
    memory_limit: Optional[int] = 262144


class TestCaseResult(BaseModel):
    """Result of a single test case execution."""
    test_case_index: int
    passed: bool
    input: str
    expected_output: str
    actual_output: str
    status: str
    time: Optional[str] = None
    memory: Optional[int] = None
    error: Optional[str] = None


class ValidationResponse(BaseModel):
    """Response from code validation."""
    total_tests: int
    passed_tests: int
    all_passed: bool
    results: List[TestCaseResult]


def prepare_code(user_code: str, boilerplate_full: str) -> str:
    """
    Replace the ##USER_CODE_HERE## placeholder with user's code.
    """
    return boilerplate_full.replace("##USER_CODE_HERE##", user_code)


def normalize_output(output: str) -> str:
    """
    Normalize output for comparison.
    - Strip leading/trailing whitespace
    - Normalize line endings
    """
    return output.strip().replace('\r\n', '\n').replace('\r', '\n')


@router.post("/validate", response_model=ValidationResponse)
async def validate_code(request: ValidationRequest):
    """
    Validate code against test cases.

    This endpoint:
    1. Combines user code with the full boilerplate
    2. Runs the code against each test case using Judge0
    3. Compares output with expected output
    4. Returns detailed results for each test case

    Args:
        request: ValidationRequest containing code, boilerplate, and test cases

    Returns:
        ValidationResponse with pass/fail status for each test case
    """
    results: List[TestCaseResult] = []
    passed_count = 0

    # Prepare the full code
    full_code = prepare_code(request.code, request.boilerplate_full)
    logger.info(f"Prepared code for execution ({len(full_code)} chars)")

    for idx, test_case in enumerate(request.test_cases):
        try:
            # Execute the code with test case input
            exec_request = ExecutionRequest(
                code=full_code,
                language=request.language,
                stdin=test_case.input,
                time_limit=request.time_limit,
                memory_limit=request.memory_limit
            )

            exec_result = await execute_code(exec_request)

            # Normalize outputs for comparison
            actual_output = normalize_output(exec_result.stdout)
            expected_output = normalize_output(test_case.expected_output)

            # Check if test passed
            passed = actual_output == expected_output

            # Build error message if any
            error = None
            if exec_result.compile_output:
                error = f"Compile Error: {exec_result.compile_output}"
            elif exec_result.stderr:
                error = f"Runtime Error: {exec_result.stderr}"
            elif exec_result.status_id != 3:  # 3 = Accepted in Judge0
                error = f"Status: {exec_result.status}"

            if passed:
                passed_count += 1

            results.append(TestCaseResult(
                test_case_index=idx,
                passed=passed,
                input=test_case.input,
                expected_output=test_case.expected_output,
                actual_output=exec_result.stdout,
                status=exec_result.status,
                time=exec_result.time,
                memory=exec_result.memory,
                error=error
            ))

        except HTTPException as e:
            # Handle execution errors
            results.append(TestCaseResult(
                test_case_index=idx,
                passed=False,
                input=test_case.input,
                expected_output=test_case.expected_output,
                actual_output="",
                status="Error",
                error=str(e.detail)
            ))

        except Exception as e:
            logger.error(f"Error executing test case {idx}: {e}")
            results.append(TestCaseResult(
                test_case_index=idx,
                passed=False,
                input=test_case.input,
                expected_output=test_case.expected_output,
                actual_output="",
                status="Error",
                error=str(e)
            ))

    return ValidationResponse(
        total_tests=len(request.test_cases),
        passed_tests=passed_count,
        all_passed=passed_count == len(request.test_cases),
        results=results
    )


@router.post("/run-single")
async def run_single_test(
    code: str,
    language: str,
    boilerplate_full: str,
    input_data: str,
    time_limit: float = 2.0,
    memory_limit: int = 262144
):
    """
    Run code with custom input (for custom test cases).

    Args:
        code: User's code
        language: Programming language
        boilerplate_full: Full boilerplate with ##USER_CODE_HERE## placeholder
        input_data: Custom input to run with
        time_limit: Time limit in seconds
        memory_limit: Memory limit in KB

    Returns:
        Execution result with stdout, stderr, and status
    """
    full_code = prepare_code(code, boilerplate_full)

    exec_request = ExecutionRequest(
        code=full_code,
        language=language,
        stdin=input_data,
        time_limit=time_limit,
        memory_limit=memory_limit
    )

    result = await execute_code(exec_request)

    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "compile_output": result.compile_output,
        "status": result.status,
        "status_id": result.status_id,
        "time": result.time,
        "memory": result.memory,
        "exit_code": result.exit_code
    }
