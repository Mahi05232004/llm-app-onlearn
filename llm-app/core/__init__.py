"""
Core infrastructure for the LLM application.

This package provides course data loading and exception handling.
"""

from core.course_data import (
    course_loader,
    get_questions,
    get_question_by_id,
    get_sidebar_data,
    get_courses,
)
from core.exceptions import DatabaseConnectionError

__all__ = [
    # Course data loader
    "course_loader",
    "get_questions",
    "get_question_by_id",
    "get_sidebar_data",
    "get_courses",
    # Exceptions  
    "DatabaseConnectionError",
]
