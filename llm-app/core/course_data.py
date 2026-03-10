"""
JSON-based course data loader.

This module replaces the Neo4j database for loading course curriculum data.
It reads from JSON files in the shared /data/courses directory.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import course_config

logger = logging.getLogger(__name__)


class CourseDataLoader:
    """Loads and caches course data from JSON files."""
    
    _instance: Optional["CourseDataLoader"] = None
    _courses_index: Optional[Dict[str, Any]] = None
    _questions_cache: Dict[str, List[Dict[str, Any]]] = {}
    
    def __new__(cls) -> "CourseDataLoader":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._load_index()
    
    def _load_index(self) -> None:
        """Load the course index file."""
        try:
            index_path = Path(course_config.index_path)
            if index_path.exists():
                with open(index_path, "r", encoding="utf-8") as f:
                    self._courses_index = json.load(f)
                logger.info(f"Loaded course index with {len(self._courses_index.get('courses', []))} courses")
            else:
                logger.warning(f"Course index not found at {index_path}")
                self._courses_index = {"courses": []}
        except Exception as e:
            logger.error(f"Error loading course index: {e}")
            self._courses_index = {"courses": []}
    
    def get_courses(self) -> List[Dict[str, Any]]:
        """Get list of all available courses."""
        return self._courses_index.get("courses", []) if self._courses_index else []
    
    def get_course(self, course_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific course by ID."""
        for course in self.get_courses():
            if course.get("id") == course_id:
                return course
        return None
    
    def get_questions(self, course_id: str = "dsa") -> List[Dict[str, Any]]:
        """Load questions for a specific course. Results are cached."""
        if course_id in self._questions_cache:
            return self._questions_cache[course_id]
        
        try:
            questions_path = Path(course_config.get_course_path(course_id))
            if questions_path.exists():
                with open(questions_path, "r", encoding="utf-8") as f:
                    questions = json.load(f)
                self._questions_cache[course_id] = questions
                logger.info(f"Loaded {len(questions)} questions for course '{course_id}'")
                return questions
            else:
                logger.warning(f"Questions file not found at {questions_path}")
                return []
        except Exception as e:
            logger.error(f"Error loading questions for course '{course_id}': {e}")
            return []
    
    def get_question_by_id(self, question_id: str, course_id: str = "dsa") -> Optional[Dict[str, Any]]:
        """Get a specific question by ID."""
        questions = self.get_questions(course_id)
        for question in questions:
            if question.get("question_id") == question_id:
                return question
        return None
    
    def get_sidebar_data(self, course_id: str = "dsa") -> List[Dict[str, Any]]:
        """
        Build hierarchical sidebar data from questions.
        Returns structure matching frontend expectations:
        [{ step_id, step_no, title, sub_steps: [{ id, sub_step_no, title, questions: [{ id, title, ... }] }] }]
        """
        questions = self.get_questions(course_id)
        
        # Build hierarchical structure
        steps_map: Dict[int, Dict[str, Any]] = {}
        
        for q in questions:
            step_no = q.get("step_no", 0)
            sub_step_no = q.get("sub_step_no", 0)
            
            # Initialize step if not exists
            if step_no not in steps_map:
                steps_map[step_no] = {
                    "step_id": f"step_{step_no}",
                    "step_no": step_no,
                    "title": q.get("step_title", ""),
                    "sub_steps": {}
                }
            
            # Initialize sub_step if not exists
            step = steps_map[step_no]
            if sub_step_no not in step["sub_steps"]:
                step["sub_steps"][sub_step_no] = {
                    "id": f"substep_{step_no}_{sub_step_no}",
                    "sub_step_no": sub_step_no,
                    "title": q.get("sub_step_title", ""),
                    "questions": []
                }
            
            # Add question to sub_step
            step["sub_steps"][sub_step_no]["questions"].append({
                "id": q.get("question_id"),
                "question_id": q.get("question_id"),
                "sl_no": q.get("sl_no"),
                "title": q.get("question_title"),
                "question_title": q.get("question_title"),
                "difficulty": q.get("difficulty"),
                "has_code": q.get("has_code", False),
            })
        
        # Convert to list format and sort
        result = []
        for step_no in sorted(steps_map.keys()):
            step = steps_map[step_no]
            sub_steps_list = []
            for sub_step_no in sorted(step["sub_steps"].keys()):
                sub_step = step["sub_steps"][sub_step_no]
                # Sort questions by sl_no
                sub_step["questions"] = sorted(sub_step["questions"], key=lambda x: x.get("sl_no", 0))
                sub_steps_list.append(sub_step)
            step["sub_steps"] = sub_steps_list
            result.append(step)
        
        return result
    
    def reload(self) -> None:
        """Force reload all data from disk."""
        self._questions_cache.clear()
        self._load_index()
        logger.info("Course data reloaded")


# Singleton instance for easy access
course_loader = CourseDataLoader()


# Convenience functions
def get_questions(course_id: str = "dsa") -> List[Dict[str, Any]]:
    """Get all questions for a course."""
    return course_loader.get_questions(course_id)


def get_question_by_id(question_id: str, course_id: str = "dsa") -> Optional[Dict[str, Any]]:
    """Get a specific question by ID."""
    return course_loader.get_question_by_id(question_id, course_id)


def get_sidebar_data(course_id: str = "dsa") -> List[Dict[str, Any]]:
    """Get sidebar navigation data for a course."""
    return course_loader.get_sidebar_data(course_id)


def get_courses() -> List[Dict[str, Any]]:
    """Get list of all available courses."""
    return course_loader.get_courses()
