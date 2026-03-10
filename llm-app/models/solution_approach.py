# models/solution_approach.py
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class SolutionApproach:
    """Represents a solution approach for a question"""

    approach_name: str
    explanation: str
    question_id: str
    solution_approach_id: Optional[str] = None

    def __post_init__(self):
        if self.solution_approach_id is None:
            # Create a unique ID based on question_id and approach_name
            self.solution_approach_id = (
                f"sa_{self.question_id}_{self.approach_name.replace(' ', '_').lower()}"
            )

    def to_dict(self) -> Dict:
        return {
            "solution_approach_id": self.solution_approach_id,
            "question_id": self.question_id,
            "approach_name": self.approach_name,
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SolutionApproach":
        return cls(
            solution_approach_id=data.get("solution_approach_id"),
            question_id=data["question_id"],
            approach_name=data["approach_name"],
            explanation=data["explanation"],
        )
