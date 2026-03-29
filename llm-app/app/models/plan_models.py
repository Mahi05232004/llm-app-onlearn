"""
Data models for the adaptive weekly planning system.

These models define the structure for student profiles, weekly plans,
progress tracking, and planning constants.
"""

from datetime import datetime, timedelta, UTC
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC).
    
    Pydantic may parse date strings like '2026-05-15' as naive datetimes.
    This helper ensures they're UTC-aware so they can be compared with
    datetime.now(UTC).
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


# Fixed time estimates (minutes) per difficulty level
DIFFICULTY_MINUTES: dict[str, int] = {
    Difficulty.EASY: 30,
    Difficulty.MEDIUM: 45,
    Difficulty.HARD: 60,
}

# Reserve 10% of weekly hours as buffer
BUFFER_PERCENT = 0.10


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class TopicStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class WeekStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class PaceStatus(str, Enum):
    AHEAD = "ahead"
    ON_TRACK = "on_track"
    BEHIND = "behind"


# ──────────────────────────────────────────────
# Student Profile (structured, replaces JSON string)
# ──────────────────────────────────────────────

class StudentProfile(BaseModel):
    """Structured student profile gathered during onboarding."""
    goal: str                          # e.g., "FAANG interviews", "placements"
    target_date: datetime              # when student wants to be ready
    weekly_hours: float                # hours per week committed
    skill_level: str                   # "beginner", "intermediate", "advanced"
    language: str                      # preferred coding language
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    learning_style: Optional[str] = None  # e.g., "prefers examples over theory"
    timeline: Optional[str] = None        # raw timeline string, e.g. "4 weeks", "3 months"

    @property
    def weekly_available_minutes(self) -> int:
        """Usable minutes per week after removing buffer."""
        total = self.weekly_hours * 60
        return int(total * (1 - BUFFER_PERCENT))

    @property
    def weekly_buffer_minutes(self) -> int:
        """Buffer minutes per week."""
        return int(self.weekly_hours * 60 * BUFFER_PERCENT)


# ──────────────────────────────────────────────
# Plan Models
# ──────────────────────────────────────────────

class PlannedTopic(BaseModel):
    """A single topic/question assigned to a week."""
    question_id: str                   # e.g., "q_1_2_3"
    title: str
    difficulty: str                    # "easy" | "medium" | "hard"
    estimated_minutes: int             # from DIFFICULTY_MINUTES
    status: TopicStatus = TopicStatus.NOT_STARTED
    completed_at: Optional[datetime] = None
    actual_minutes: Optional[int] = None

    @classmethod
    def from_question(cls, question: dict) -> "PlannedTopic":
        """Create a PlannedTopic from a curriculum question dict."""
        difficulty = question.get("difficulty", "medium").lower()
        return cls(
            question_id=question["question_id"],
            title=question.get("question_title", question.get("title", "")),
            difficulty=difficulty,
            estimated_minutes=DIFFICULTY_MINUTES.get(difficulty, 45),
        )


class WeekPlan(BaseModel):
    """A single week in the learning plan."""
    week_number: int
    start_date: datetime
    end_date: datetime
    focus_area: str                    # set by LLM planner (e.g., "Arrays & Hashing")
    planned_minutes: int               # sum of topic estimates
    buffer_minutes: int                # 10% of weekly budget
    topics: list[PlannedTopic] = Field(default_factory=list)
    status: WeekStatus = WeekStatus.NOT_STARTED

    @property
    def completed_topics(self) -> int:
        return sum(1 for t in self.topics if t.status == TopicStatus.COMPLETED)

    @property
    def total_estimated_minutes(self) -> int:
        return sum(t.estimated_minutes for t in self.topics)

    @property
    def remaining_minutes(self) -> int:
        """Minutes of capacity remaining in this week."""
        return self.planned_minutes - self.total_estimated_minutes


class LearningPlan(BaseModel):
    """The full learning plan containing all weeks."""
    weeks: list[WeekPlan] = Field(default_factory=list)
    total_topics: int = 0
    plan_version: int = 1              # increments on each update
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def total_weeks(self) -> int:
        return len(self.weeks)

    @property
    def completed_topics_count(self) -> int:
        return sum(w.completed_topics for w in self.weeks)

    def get_current_week(self) -> Optional[WeekPlan]:
        """Get the current active week based on today's date."""
        now = datetime.now(UTC)
        for week in self.weeks:
            start = _ensure_utc(week.start_date)
            end = _ensure_utc(week.end_date)
            if start <= now <= end:
                return week
        # If past all weeks, return last incomplete week
        for week in self.weeks:
            if week.status != WeekStatus.COMPLETED:
                return week
        return None

    def find_topic(self, question_id: str) -> tuple[Optional[WeekPlan], Optional[PlannedTopic]]:
        """Find which week a topic is planned in."""
        for week in self.weeks:
            for topic in week.topics:
                if topic.question_id == question_id:
                    return week, topic
        return None, None


# ──────────────────────────────────────────────
# Progress Tracking
# ──────────────────────────────────────────────

class Progress(BaseModel):
    """Progress metrics for the student's learning journey."""
    total_topics: int = 0
    completed_topics: int = 0
    completion_percentage: float = 0.0
    days_elapsed: int = 0
    days_remaining: int = 0
    topics_per_week_expected: float = 0.0
    topics_per_week_actual: float = 0.0
    pace_status: PaceStatus = PaceStatus.ON_TRACK
    pace_message: str = ""
    estimated_completion: Optional[datetime] = None
    started_at: Optional[datetime] = None
    target_date: Optional[datetime] = None
    streak: int = 0

    @classmethod
    def calculate(
        cls,
        plan: LearningPlan,
        profile: StudentProfile,
        started_at: datetime,
    ) -> "Progress":
        """Calculate progress from current plan state."""
        now = datetime.now(UTC)
        total = plan.total_topics
        completed = plan.completed_topics_count

        started_utc = _ensure_utc(started_at)
        target_utc = _ensure_utc(profile.target_date)

        # Defensive: if target_date is before or equal to started_at
        # (stale onboarding date), recompute from plan duration so
        # progress metrics stay meaningful instead of showing "X days behind".
        if target_utc <= started_utc:
            total_weeks = plan.total_weeks or 12
            target_utc = started_utc + timedelta(weeks=total_weeks)

        days_elapsed = max((now - started_utc).days, 1)
        days_remaining = max((target_utc - now).days, 0)
        weeks_elapsed = max(days_elapsed / 7, 1)

        topics_per_week_actual = completed / weeks_elapsed
        total_weeks = plan.total_weeks or 1
        topics_per_week_expected = total / total_weeks

        # Determine pace
        if topics_per_week_actual >= topics_per_week_expected * 1.1:
            pace_status = PaceStatus.AHEAD
            days_ahead = int((topics_per_week_actual - topics_per_week_expected) * 7)
            pace_message = f"You're {days_ahead} days ahead of schedule! 🔥"
        elif topics_per_week_actual >= topics_per_week_expected * 0.9:
            pace_status = PaceStatus.ON_TRACK
            pace_message = "You're right on track! ✅"
        else:
            pace_status = PaceStatus.BEHIND
            days_behind = int((topics_per_week_expected - topics_per_week_actual) * 7)
            pace_message = f"You're about {days_behind} days behind schedule. Let's catch up! ⚠️"

        # Estimate completion based on actual pace
        if topics_per_week_actual > 0:
            remaining_topics = total - completed
            remaining_weeks = remaining_topics / topics_per_week_actual
            estimated_completion = now + timedelta(weeks=remaining_weeks)
        else:
            estimated_completion = target_utc

        return cls(
            total_topics=total,
            completed_topics=completed,
            completion_percentage=round((completed / total * 100) if total > 0 else 0, 1),
            days_elapsed=days_elapsed,
            days_remaining=days_remaining,
            topics_per_week_expected=round(topics_per_week_expected, 1),
            topics_per_week_actual=round(topics_per_week_actual, 1),
            pace_status=pace_status,
            pace_message=pace_message,
            estimated_completion=estimated_completion,
            started_at=started_utc,
            target_date=target_utc,
        )
