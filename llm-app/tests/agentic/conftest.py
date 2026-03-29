"""
Shared fixtures for the agentic test suite.

Provides:
- InMemoryStore for isolated workspace tests
- Agent creation helpers
- Test data factories
"""

import os
import sys
import uuid

import pytest

# Ensure llm-app root is on the path so `app.*` imports work
_LLM_APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _LLM_APP_ROOT not in sys.path:
    sys.path.insert(0, _LLM_APP_ROOT)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def in_memory_store():
    """Provide a fresh InMemoryStore for workspace tests."""
    from langgraph.store.memory import InMemoryStore

    return InMemoryStore()


@pytest.fixture
def test_user_id():
    """Generate a unique test user ID."""
    return f"test_user_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def sample_question_data():
    """Standard question data for testing context formatting."""
    return {
        "question_title": "Two Sum",
        "difficulty": "easy",
        "question_type": "coding",
        "has_code": True,
        "step_title": "Arrays & Hashing",
        "sub_step_title": "Hash Map Lookup",
        "concepts": ["hash map", "complementary pairs", "O(n) lookup"],
        "question": (
            "Given an array of integers nums and an integer target, "
            "return indices of the two numbers that add up to target."
        ),
        "solution_approaches": [
            {
                "approach_name": "Brute Force",
                "explanation": "Check every pair with nested loops. O(n^2).",
            },
            {
                "approach_name": "Hash Map",
                "explanation": "Store seen numbers in a dict. O(n).",
            },
        ],
    }


@pytest.fixture
def sample_code_context():
    """Standard code context for testing code-mode formatting."""
    return {
        "problemTitle": "Two Sum",
        "problemDescription": "Find two numbers that add up to target.",
        "constraints": "2 <= nums.length <= 10^4",
        "expectedTc": "O(n)",
        "language": "python",
        "labCode": "def twoSum(nums, target):\n    pass",
    }


@pytest.fixture
def sample_learn_code_context():
    """Scratchpad code context for learn-mode."""
    return {
        "language": "python",
        "learnCode": "# my scratch code\nfor i in range(10):\n    print(i)",
    }


@pytest.fixture
def sample_tutor_context(sample_question_data):
    """Full tutor_context dict as it would be passed to the agent."""
    return {
        "mode": "learn",
        "module": "dsa",
        "question_data": sample_question_data,
        "code_context": None,
        "last_interaction_at": None,
    }
