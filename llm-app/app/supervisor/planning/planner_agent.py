"""
LLM Planner Agent.

A lightweight LLM agent (flash model) that takes a student profile and
the full curriculum structure, then outputs an intelligently ordered list
of topics with focus area groupings.

The planner agent handles the *thinking* part:
- Which topics to include based on student's timeline and level
- What order to do them in (prerequisites, building complexity)
- How to group them into focus areas

The rule-based PlanBuilder then handles the *mechanical* part:
- Packing topics into weeks based on time budgets
"""

import json
import logging
from typing import Any

from app.supervisor.config import get_onboarding_model
from core.course_data import get_sidebar_data

logger = logging.getLogger(__name__)


PLANNER_PROMPT = """You are a learning plan generator. Your job is to create a REALISTIC, DEADLINE-AWARE learning plan that fits within the student's available time.

## CRITICAL RULES — Read First

0. **FILL THE BUDGET**: The student has allocated specific time (e.g., 12 weeks). Do NOT create a 6-week plan if they have 12 weeks. Use the available time to go DEEPER. Add more practice problems, variations, and advanced concepts to fill the timeline.
1. **RESPECT THE DEADLINE**: You will be given the number of available weeks and total available minutes. You MUST NOT exceed this. If the student has 13 weeks, the plan MUST fit in 13 weeks. Period.
2. **SELECT, DON'T DUMP**: You must CHOOSE the most impactful topics. A 3-month plan with 80 carefully selected topics is far better than cramming 440 topics into 48 weeks. But if you have the time, include 150 topics!
3. **PRIORITIZE BY GOAL**: If the student's goal is interviews/placements, focus on the most-asked patterns. If the goal is fundamentals, be more comprehensive. Adapt to the domain — for DSA this means common patterns like Arrays, Two Pointers, Trees, DP; for Data Science this means core math, statistics, and ML fundamentals.
4. **RESPECT STRENGTHS**: If the student is strong in a topic, skip the basics. Instead, select 1-2 **HARD/CHALLENGE** problems to test their mastery, then move on. Don't waste time on easy stuff they know.
5. **FOCUS ON WEAKNESSES**: Allocate MORE time to areas the student identified as weak. These need more practice problems.
6. **PREREQUISITES MATTER**: Include foundational topics that are prerequisites for harder ones (e.g., recursion before trees/DP), even if the student didn't mention them as weak areas.
7. **QUALITY OVER QUANTITY**: For each topic area, pick the most representative and educational problems.

## Your Task

1. Review the student's profile: goal, deadline, weekly hours, skill level, strengths, weaknesses
2. Calculate how many topics can realistically fit based on the time budget provided
3. Select and order specific topics. **AIM TO FILL cca 90% OF THE TIME BUDGET.**
4. Group selected topics into focus areas
5. List skipped topic areas with brief reasons

## Difficulty Time Estimates
- Easy: 30 minutes
- Medium: 45 minutes  
- Hard: 60 minutes

## Output Format

Return a JSON object with exactly this structure:
```json
{
  "ordered_topics": ["q_1_1_1", "q_1_1_2", ...],
  "focus_areas": [
    {"label": "Arrays & Basics", "topics": ["q_1_1_1", "q_1_1_2"]},
    ...
  ],
  "skipped_areas": [
    {"area": "Advanced Graph Theory", "reason": "Not enough time; fundamentals prioritized"},
    ...
  ],
  "reasoning": "Explanation of selection strategy and why certain topics were prioritized/skipped"
}
```

IMPORTANT:
- Only return valid JSON, no markdown formatting
- Use the exact question_id values from the curriculum
- Every topic in ordered_topics must appear in exactly one focus_area
- The total estimated time for ALL selected topics MUST fit within the time budget
- It's OK (and expected) to skip entire sections if time is limited
"""


async def generate_topic_ordering(
    student_profile: dict[str, Any],
    curriculum: list[dict[str, Any]] | None = None,
    feedback: str | None = None,
    available_weeks: int | None = None,
    total_budget_minutes: int | None = None,
    course_id: str = "dsa",
) -> dict[str, Any]:
    """
    Use the LLM planner to generate an intelligent topic ordering.

    Args:
        student_profile: Student's profile data (goal, timeline, skill level, etc.)
        curriculum: Optional pre-loaded curriculum data. If None, loads from course_data.
        feedback: Optional student feedback on a previous plan.
        available_weeks: Number of weeks until the deadline.
        total_budget_minutes: Total minutes available across all weeks.

    Returns:
        Dict with 'ordered_topics' (list of question_ids),
        'focus_areas' (list of {label, topics}), and 'reasoning'
    """
    if curriculum is None:
        curriculum = get_sidebar_data(course_id=course_id)

    # Build a compact curriculum summary for the LLM
    curriculum_summary = _build_curriculum_summary(curriculum)

    model = get_onboarding_model()  # Flash model — fast and cheap

    message = f"""## Student Profile
{json.dumps(student_profile, indent=2, default=str)}
"""

    # Add explicit time budget if available
    if available_weeks and total_budget_minutes:
        weekly_hours = student_profile.get("weekly_hours", 10)
        message += f"""
## ⏰ Time Budget (HARD CONSTRAINT)
- **Available weeks**: {available_weeks} weeks
- **Weekly study hours**: {weekly_hours} hours/week
- **Total budget**: {total_budget_minutes} minutes ({round(total_budget_minutes / 60)} hours)
- You MUST select topics that fit within {total_budget_minutes} total minutes
- Easy = 30 min, Medium = 45 min, Hard = 60 min
- Example: {total_budget_minutes} min ≈ {total_budget_minutes // 90} medium problems or {total_budget_minutes // 40} easy problems
"""

    message += f"""
## Full Curriculum
{curriculum_summary}
"""

    if feedback:
        message += f"""\n## Student Feedback on Previous Plan
The student reviewed the previous plan and requested these changes:
\"\"\"
{feedback}
\"\"\"
Please adjust the topic ordering and focus areas to incorporate this feedback.
"""

    message += "\nGenerate the optimal topic ordering for this student. Return only valid JSON."

    try:
        response = await model.ainvoke([
            ("system", PLANNER_PROMPT),
            ("human", message),
        ])

        # Parse the LLM's JSON response
        content = response.content
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )

        # Clean up potential markdown code fences
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]  # Remove first line
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        result = json.loads(content)

        # Validate structure
        if "ordered_topics" not in result or "focus_areas" not in result:
            raise ValueError("Missing required fields in planner response")

        # CRITICAL: Enforce curriculum order
        # The LLM selects the *set* of topics, but we strictly enforce the *sequence*
        # from the official curriculum (e.g. Arrays -> LL -> Trees -> DP).
        # This prevents "DP before Graphs" issues.
        result = _enforce_curriculum_order(result, curriculum)

        logger.info(
            f"Planner generated ordering: {len(result['ordered_topics'])} topics, "
            f"{len(result['focus_areas'])} focus areas"
        )
        return result

    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to parse planner response: {e}")
        # Fallback: return topics in curriculum order
        return _fallback_ordering(curriculum)

    except Exception as e:
        logger.error(f"Planner agent error: {e}", exc_info=True)
        return _fallback_ordering(curriculum)


def _build_curriculum_summary(curriculum: list[dict]) -> str:
    """Build a compact text summary of the curriculum for the LLM."""
    lines = []
    for step in curriculum:
        step_no = step.get("step_no", 0)
        step_title = step.get("title", "")
        lines.append(f"\n### Step {step_no}: {step_title}")

        for sub_step in step.get("sub_steps", []):
            sub_no = sub_step.get("sub_step_no", 0)
            sub_title = sub_step.get("title", "")
            lines.append(f"  Sub-step {step_no}.{sub_no}: {sub_title}")

            for q in sub_step.get("questions", []):
                qid = q.get("question_id", q.get("id", ""))
                qtitle = q.get("question_title", q.get("title", ""))
                diff = q.get("difficulty", "medium")
                lines.append(f"    - [{diff}] {qid}: {qtitle}")

    return "\n".join(lines)


def _fallback_ordering(curriculum: list[dict]) -> dict:
    """Fallback: return topics in their natural curriculum order."""
    ordered = []
    focus_areas = []

    for step in curriculum:
        step_title = step.get("title", "General")
        step_topics = []

        for sub_step in step.get("sub_steps", []):
            for q in sub_step.get("questions", []):
                qid = q.get("question_id", q.get("id", ""))
                if qid:
                    ordered.append(qid)
                    step_topics.append(qid)

        if step_topics:
            focus_areas.append({"label": step_title, "topics": step_topics})

    logger.warning(f"Using fallback ordering: {len(ordered)} topics")
    return {
        "ordered_topics": ordered,
        "focus_areas": focus_areas,
        "reasoning": "Fallback: topics in curriculum order",
    }


def _enforce_curriculum_order(llm_result: dict, curriculum: list[dict]) -> dict:
    """
    Re-order the LLM's selected topics to strictly follow the curriculum sequence.

    The LLM is great at selection (what to study) but can hallucinate the order
    (e.g., putting DP before Greedy). We fix this by:
    1. Building a global index of the curriculum (ordering of all questions)
    2. Sorting the LLM's 'ordered_topics' based on this index
    3. Sorting topics within each 'focus_area'
    4. Sorting the 'focus_areas' themselves based on the first topic in each area
    """
    ordered_ids = llm_result.get("ordered_topics", [])
    focus_areas = llm_result.get("focus_areas", [])
    skipped_areas = llm_result.get("skipped_areas", [])
    reasoning = llm_result.get("reasoning", "")

    # 1. Build global index from curriculum
    # Map question_id -> global index (0, 1, 2...)
    question_index_map = {}
    idx_counter = 0

    # Handle curriculum structure: steps -> sub_steps -> questions
    # Sometimes 'curriculum' is the compact sidebar data structure
    for step in curriculum:
        # Steps might just have questions directly if flat, but usually nested
        sub_steps = step.get("sub_steps", [])
        if not sub_steps:
             # Try flat structure just in case
             for q in step.get("questions", []):
                qid = q.get("question_id", q.get("id", ""))
                if qid:
                    question_index_map[qid] = idx_counter
                    idx_counter += 1
        
        for sub_step in sub_steps:
            for q in sub_step.get("questions", []):
                qid = q.get("question_id", q.get("id", ""))
                if qid:
                    question_index_map[qid] = idx_counter
                    idx_counter += 1

    # 2. Sort 'ordered_topics'
    valid_topics = [tid for tid in ordered_ids if tid in question_index_map]
    
    # If no valid topics found (unlikely), keep original order to avoid empty plan
    if not valid_topics and ordered_ids:
        logger.warning("LLM generated topics not found in curriculum index. Keeping original order.")
        sorted_topics = ordered_ids
    elif valid_topics:
        # Sort based on index
        sorted_topics = sorted(valid_topics, key=lambda tid: question_index_map[tid])
    else:
        sorted_topics = []

    # 3. Sort topics within 'focus_areas' and sort the areas themselves
    sorted_focus_areas = []
    
    for area in focus_areas:
        # Sort topics inside the area
        area_topics = area.get("topics", [])
        # Only keep valid topics (or keep all if none predictable? safer to filter)
        valid_area_topics = [t for t in area_topics if t in question_index_map]
        
        if valid_area_topics:
            area["topics"] = sorted(valid_area_topics, key=lambda tid: question_index_map[tid])
            sorted_focus_areas.append(area)
        else:
            # Keep area if it has topics but they weren't found in index (fallback)
            sorted_focus_areas.append(area)

    # Sort focus areas based on first topic's index
    def get_area_start_index(area_obj):
        topics = area_obj.get("topics", [])
        if not topics or topics[0] not in question_index_map:
            return 999999 
        return question_index_map[topics[0]]

    sorted_focus_areas.sort(key=get_area_start_index)

    return {
        "ordered_topics": sorted_topics,
        "focus_areas": sorted_focus_areas,
        "skipped_areas": skipped_areas,
        "reasoning": reasoning
    }
