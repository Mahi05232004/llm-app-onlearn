# models/question.py
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


class CompletionStatus(Enum):
    NOT_ATTEMPTED = "not_attempted"
    ATTEMPTED = "attempted"
    SOLVED = "solved"


class Difficulty(Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass
class Question:
    """Represents a DSA question with all properties"""
@dataclass
class Question:
    question_id: Optional[str] = None
    question_title: Optional[str] = None
    difficulty: Optional[Difficulty] = None
    step_number: Optional[int] = None
    sub_step_number: Optional[int] = None
    sequence_number: Optional[int] = None
    standard_concepts: List[str] = field(default_factory=list)
    sub_concepts: List[str] = field(default_factory=list)
    concepts: List[str] = field(default_factory=list)
    question: Optional[str] = None
    step_title: Optional[str] = None
    sub_step_title: Optional[str] = None
    question_topic: Optional[str] = None

    def __post_init__(self):
        if self.question_id is None:
            self.question_id = f"q_{self.step_no}_{self.sub_step_no}_{self.sl_no}"

    def get_related_concepts(self) -> List[str]:
        """Get all clean concepts related to this question"""
        return self.concepts.copy()

    def to_dict(self) -> Dict:
        return {
            "question_id": self.question_id,
            "sl_no": self.sequence_number,
            "step_no": self.step_number,
            "sub_step_no": self.sub_step_number,
            "question_title": self.question_title,
            "difficulty": self.difficulty,
            "question_topic": self.question_topic,
            "concepts": self.concepts,
            "sub_concepts": self.sub_concepts,
            "standard_concepts": self.standard_concepts,
        }


@dataclass
class QuestionProgress:
    """Represents student's progress on a specific question"""

    question_id: str
    completion_status: CompletionStatus = CompletionStatus.NOT_ATTEMPTED
    last_attempt: Optional[datetime] = None
    attempts_count: int = 0
    notes: str = ""

    def mark_attempted(self):
        """Mark question as attempted"""
        self.completion_status = CompletionStatus.ATTEMPTED
        self.last_attempt = datetime.now()
        self.attempts_count += 1

    def mark_solved(self):
        """Mark question as solved"""
        self.completion_status = CompletionStatus.SOLVED
        self.last_attempt = datetime.now()
        if self.attempts_count == 0:
            self.attempts_count = 1

    def to_dict(self) -> Dict:
        return {
            "question_id": self.question_id,
            "completion_status": self.completion_status.value,
            "last_attempt": (
                self.last_attempt.isoformat() if self.last_attempt else None
            ),
            "attempts_count": self.attempts_count,
            "notes": self.notes,
        }
