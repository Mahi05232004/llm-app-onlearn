# models/student.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from models.concept import ConceptMastery
from models.question import CompletionStatus, QuestionProgress


@dataclass
class Student:
    """Represents a student with their progress and mastery"""

    username: str
    name: str
    email: Optional[str] = None
    question_progress: Dict[str, QuestionProgress] = field(default_factory=dict)
    concept_mastery: Dict[str, ConceptMastery] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
