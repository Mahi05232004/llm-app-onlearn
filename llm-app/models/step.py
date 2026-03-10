from dataclasses import dataclass, field
from typing import Dict, List, Optional

from models.question import Difficulty, Question


@dataclass
class SubStep:
    """Represents a sub-step within a step"""

    sub_step_no: int
    sub_step_title: str
    questions: List[Question] = field(default_factory=list)
    sub_step_id: Optional[str] = None

    def __post_init__(self):
        if self.sub_step_id is None:
            self.sub_step_id = (
                f"substep_{self.sub_step_title.replace(' ', '_').lower()}"
            )

    def add_question(self, question: Question):
        """Add a question to this sub-step"""
        self.questions.append(question)

    def get_questions_by_difficulty(self, difficulty: Difficulty) -> List[Question]:
        """Get questions filtered by difficulty"""
        return [q for q in self.questions if q.difficulty == difficulty]

    def to_dict(self) -> Dict:
        return {
            "sub_step_id": self.sub_step_id,
            "sub_step_no": self.sub_step_no,
            "sub_step_title": self.sub_step_title,
            "questions": [q.to_dict() for q in self.questions],
        }


@dataclass
class Step:
    """Represents a main step in the learning path"""

    step_no: int
    step_title: str
    sub_steps: List[SubStep] = field(default_factory=list)
    step_id: Optional[str] = None

    def __post_init__(self):
        if self.step_id is None:
            self.step_id = f"step_{self.step_no}"

    def add_sub_step(self, sub_step: SubStep):
        """Add a sub-step to this step"""
        self.sub_steps.append(sub_step)

    def get_all_questions(self) -> List[Question]:
        """Get all questions from all sub-steps"""
        questions = []
        for sub_step in self.sub_steps:
            questions.extend(sub_step.questions)
        return questions

    def to_dict(self) -> Dict:
        return {
            "step_id": self.step_id,
            "step_no": self.step_no,
            "step_title": self.step_title,
            "sub_steps": [sub_step.to_dict() for sub_step in self.sub_steps],
        }
