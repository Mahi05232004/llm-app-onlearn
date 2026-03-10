"""Agent system prompts."""

from .master import MASTER_PROMPT
from .concept_tutor import CONCEPT_TUTOR_PROMPT
from .lab_mentor import LAB_MENTOR_PROMPT
from .guide import GUIDE_AGENT_PROMPT
from .guide_ds import GUIDE_DS_AGENT_PROMPT

__all__ = [
    "MASTER_PROMPT",
    "CONCEPT_TUTOR_PROMPT", 
    "LAB_MENTOR_PROMPT",
    "GUIDE_AGENT_PROMPT",
    "GUIDE_DS_AGENT_PROMPT",
]
