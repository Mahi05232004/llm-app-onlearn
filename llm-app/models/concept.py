from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class Concept:
    """Represents a clean, standardized concept node"""

    concept_name: str
    student_description: Optional[str] = None

    def __post_init__(self):
        if self.concept_id is None:
            # Generate ID from name (normalized)
            self.concept_id = (
                self.concept_name.lower().replace(" ", "_").replace("-", "_")
            )

    def to_dict(self) -> Dict:
        return {
            "concept_id": self.concept_id,
            "concept_name": self.concept_name,
            "student_description": self.student_description,
        }


@dataclass
class ConceptMastery:
    """Represents student's mastery of a concept"""

    concept_name: str
    is_mastered: bool = False
    questions_solved: List[str] = field(default_factory=list)  # question_ids
    mastered_date: Optional[datetime] = None

    def add_solved_question(self, question_id: str):
        """Add a solved question and check for mastery"""
        if question_id not in self.questions_solved:
            self.questions_solved.append(question_id)

        # Check if concept is mastered (2+ questions solved)
        if len(self.questions_solved) >= 2 and not self.is_mastered:
            self.is_mastered = True
            self.mastered_date = datetime.now()

    def to_dict(self) -> Dict:
        return {
            "concept_name": self.concept_name,
            "is_mastered": self.is_mastered,
            "questions_solved": self.questions_solved,
            "mastered_date": (
                self.mastered_date.isoformat() if self.mastered_date else None
            ),
        }
