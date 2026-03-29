"""complete_onboarding tool — Tutor agent version."""

import json
from datetime import datetime, timedelta
from typing import Annotated, List, Optional
from langchain_core.tools import tool
from pydantic import BaseModel, Field

class OnboardingInput(BaseModel):
    goal: str = Field(description="The student's primary learning goal (e.g. 'Placement', 'Job Switch').")
    timeline: str = Field(description="The duration or deadline (e.g. '3 months', '4 weeks').")
    weekly_hours: float = Field(description="Hours per week committed to learning.")
    skill_level: str = Field(description="Current skill level (e.g. 'Beginner', 'Intermediate').")
    language: str = Field(description="Preferred programming language.")
    strengths: List[str] = Field(description="List of topic strengths (must be a list of strings).")
    weaknesses: List[str] = Field(description="List of topic weaknesses (must be a list of strings).")
    target_date: Optional[str] = Field(
        default=None, 
        description="Calculated key target date (YYYY-MM-DD). If not provided, will be calculated from timeline."
    )

@tool(args_schema=OnboardingInput)
def complete_onboarding(
    goal: str,
    timeline: str,
    weekly_hours: float,
    skill_level: str,
    language: str,
    strengths: List[str],
    weaknesses: List[str],
    target_date: Optional[str] = None,
) -> str:
    """
    Call this when the student has provided all necessary info.
    
    This tool captures the structured profile and triggers the plan generation phase.
    """
    
    # Calculate target_date if missing
    if not target_date:
        # Simple heuristic: parsed from timeline or default to 3 months
        # The frontend/planner will refine this, but we need a valid date for the model
        try:
            if "month" in timeline.lower():
                num = int(''.join(filter(str.isdigit, timeline))) or 3
                target_dt = datetime.now() + timedelta(days=num*30)
            elif "week" in timeline.lower():
                num = int(''.join(filter(str.isdigit, timeline))) or 12
                target_dt = datetime.now() + timedelta(weeks=num)
            else:
                target_dt = datetime.now() + timedelta(days=90) # Default 3 months
        except:
            target_dt = datetime.now() + timedelta(days=90)
            
        target_date = target_dt.strftime("%Y-%m-%d")

    # Construct the profile object
    profile = {
        "goal": goal,
        "timeline": timeline,
        "target_date": target_date,
        "weekly_hours": weekly_hours,
        "skill_level": skill_level,
        "language": language,
        "strengths": strengths,
        "weaknesses": weaknesses
    }

    return json.dumps({
        "status": "onboarding_complete",
        "student_profile": profile,
    })