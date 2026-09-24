"""
obe_schemas.py
Pydantic Data Contracts for Outcome-Based Education (OBE) Syllabi.
Includes intermediate chunk schemas and strict K/S/A validation.
"""

import re
from typing import List, Literal, Any
from pydantic import BaseModel, Field, field_validator, model_validator

PROHIBITED_BLOOM_VERBS = {
    "understand", "know", "learn", "appreciate", "familiarize",
    "study", "comprehend", "be aware of", "gain knowledge", "perceive"
}

BLOOM_LEVEL_MAP = {
    "designing": "Creating",
    "creating": "Creating",
    "evaluating": "Evaluating",
    "analyzing": "Analyzing",
    "applying": "Applying",
    "implementing": "Applying",
    "executing": "Applying",
    "understanding": "Understanding",
    "remembering": "Remembering"
}


# =====================================================================
# 1. CORE SCHEMAS
# =====================================================================

class CourseMetadataSchema(BaseModel):
    course_code: str = Field(..., description="Institutional course code")
    course_title: str = Field(..., description="Full descriptive title")
    credit_units: float = Field(..., gt=0)
    lecture_hours: int = Field(2, ge=0)
    lab_hours: int = Field(0, ge=0)
    prerequisites: str = Field("None")
    course_description: str = Field(...)
    semester: str = Field("1st Semester")
    academic_year: str = Field("2026-2027")

    @model_validator(mode="before")
    @classmethod
    def handle_metadata_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "course_description" not in data and "description" in data:
                data["course_description"] = data["description"]
            if "course_description" not in data:
                data["course_description"] = "Comprehensive Outcome-Based Education course syllabus."
        return data


class CourseOutcomeSchema(BaseModel):
    clo_id: str = Field(..., description="e.g., CLO1")
    statement: str = Field(..., min_length=15)
    bloom_domain: Literal["Cognitive", "Psychomotor", "Affective"] = Field("Cognitive")
    bloom_level: Literal["Remembering", "Understanding", "Applying", "Analyzing", "Evaluating", "Creating"] = Field(...)
    po_mapping: List[str] = Field(..., min_items=1)

    @field_validator("bloom_domain", mode="before")
    @classmethod
    def normalize_bloom_domain(cls, v: str) -> str:
        s = str(v).strip().capitalize()
        if s in ["Cognitive", "Psychomotor", "Affective"]:
            return s
        if s in ["Creating", "Analyzing", "Evaluating", "Understanding", "Remembering"]:
            return "Cognitive"
        if s in ["Applying", "Implementing", "Operating"]:
            return "Psychomotor"
        return "Cognitive"

    @field_validator("bloom_level", mode="before")
    @classmethod
    def normalize_bloom_level(cls, v: str) -> str:
        cleaned = str(v).strip().lower()
        if cleaned in BLOOM_LEVEL_MAP:
            return BLOOM_LEVEL_MAP[cleaned]
        return v.capitalize() if v else "Applying"

    @field_validator("statement")
    @classmethod
    def validate_active_blooms_verb(cls, v: str) -> str:
        words = re.findall(r"\b[a-zA-Z]+\b", v.lower())
        if not words:
            raise ValueError("Outcome statement cannot be empty.")
        first_word = words[0]
        if first_word == "to" and len(words) > 1:
            first_word = words[1]
        if first_word in PROHIBITED_BLOOM_VERBS:
            raise ValueError(f"Prohibited passive verb '{first_word}' detected in statement: '{v}'.")
        return v


class LessonOutcomeSchema(BaseModel):
    llo_id: str = Field(...)
    statement: str = Field(..., min_length=10)
    domain_category: Literal["K", "S", "A"] = Field(...)
    bloom_verb: str = Field(...)

    @field_validator("domain_category", mode="before")
    @classmethod
    def normalize_domain_category(cls, v: str) -> str:
        cat = str(v).strip().upper()
        if cat in ["KNOWLEDGE", "COGNITIVE"]:
            return "K"
        if cat in ["SKILL", "SKILLS", "PSYCHOMOTOR"]:
            return "S"
        if cat in ["ATTITUDE", "AFFECTIVE"]:
            return "A"
        return cat if cat in ["K", "S", "A"] else "K"

    @field_validator("statement")
    @classmethod
    def validate_active_verb_llo(cls, v: str) -> str:
        words = re.findall(r"\b[a-zA-Z]+\b", v.lower())
        if not words:
            raise ValueError("LLO statement cannot be empty.")
        first_word = words[0]
        if first_word in PROHIBITED_BLOOM_VERBS:
            raise ValueError(f"LLO statement uses unmeasurable verb '{first_word}'.")
        return v


class WeeklyScheduleSchema(BaseModel):
    week_number: int = Field(..., ge=1, le=18)
    topics: List[str] = Field(..., min_items=1)
    intended_learning_outcomes: List[LessonOutcomeSchema] = Field(..., min_items=3)
    teaching_learning_activities: List[str] = Field(..., min_items=1)
    assessment_tasks: List[str] = Field(..., min_items=1)
    resources_references: List[str] = Field(..., min_items=1)
    mapped_clos: List[str] = Field(..., min_items=1)

    @model_validator(mode="after")
    def validate_ksa_completeness(self):
        """Strictly enforces that Knowledge (K), Skills (S), and Attitude (A) are all present."""
        present = {llo.domain_category for llo in self.intended_learning_outcomes}
        missing = {"K", "S", "A"} - present
        if missing:
            raise ValueError(
                f"OBE Non-Compliance: Week {self.week_number} is missing required categories: {sorted(missing)}."
            )
        return self


# =====================================================================
# 2. INTERMEDIATE CHUNK SCHEMAS (TWO-STAGE GENERATION)
# =====================================================================

class MacroBlueprintSchema(BaseModel):
    """Stage 1: Validates the high-level roadmap."""
    metadata: CourseMetadataSchema
    course_outcomes: List[CourseOutcomeSchema] = Field(..., min_items=3, max_items=6)
    weekly_topic_roadmap: List[str] = Field(
        ..., min_items=18, max_items=18,
        description="Exactly 18 topic strings representing Weeks 1 through 18."
    )

    @field_validator("weekly_topic_roadmap", mode="before")
    @classmethod
    def ensure_eighteen_topics(cls, v: Any) -> Any:
        if isinstance(v, list):
            # Auto-pad or trim to 18 if LLM slightly miscounts
            if len(v) < 18:
                while len(v) < 18:
                    v.append(f"Advanced Topics and Applications Part {len(v)+1}")
            elif len(v) > 18:
                v = v[:18]
        return v


class ScheduleChunkSchema(BaseModel):
    """Stage 2: Validates a 9-week half (Weeks 1-9 or Weeks 10-18)."""
    schedules: List[WeeklyScheduleSchema] = Field(..., min_items=9, max_items=9)


# =====================================================================
# 3. FULL SYLLABUS CONTRACT
# =====================================================================

class FullSyllabusSchema(BaseModel):
    metadata: CourseMetadataSchema
    course_outcomes: List[CourseOutcomeSchema] = Field(..., min_items=3, max_items=6)
    weekly_schedules: List[WeeklyScheduleSchema] = Field(..., min_items=18, max_items=18)

    @field_validator("course_outcomes", mode="before")
    @classmethod
    def trim_course_outcomes(cls, v: Any) -> Any:
        if isinstance(v, list) and len(v) > 6:
            return v[:6]
        return v

    @model_validator(mode="after")
    def validate_full_term_structure(self):
        weeks = [w.week_number for w in self.weekly_schedules]
        if sorted(weeks) != list(range(1, 19)):
            raise ValueError(f"Syllabus must have exactly 18 weeks (1-18). Found: {sorted(weeks)}")
        return self