"""
llm_engine.py
Two-Stage Chunked Generation Engine with Adaptive Model Routing & Single-Model Laptop Fallback.
"""

import json
import logging
import requests
from typing import List, Optional
from pydantic import ValidationError
from obe_schemas import (
    FullSyllabusSchema,
    MacroBlueprintSchema,
    ScheduleChunkSchema,
    WeeklyScheduleSchema
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LLMEngine")

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_GENERATE_ENDPOINT = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_TAGS_ENDPOINT = f"{OLLAMA_BASE_URL}/api/tags"

OBE_SYSTEM_PROMPT = """
You are a Commission on Higher Education (CHED) Outcome-Based Education (OBE) curriculum specialist 
for the College of Computer Studies (CCS).
CRITICAL RULES:
1. All CLO and LLO outcomes must commence with active, measurable Bloom's Taxonomy verbs (Analyze, Design, Implement, Formulate, Evaluate).
2. Strictly forbid passive/unmeasurable verbs ('understand', 'know', 'learn', 'appreciate').
3. Always respond in valid, parseable JSON conforming strictly to the requested schema.
"""


# =====================================================================
# ADAPTIVE MODEL ROUTER (Self-Configuring / Laptop-Safe)
# =====================================================================

class ModelRouter:
    """
    Auto-discovers installed Ollama models via GET /api/tags.
    - If multiple models exist: routes Stage 1 to a fast model and Stage 2 to a smart model.
    - If only 1 model exists (e.g., on a laptop): collapses safely to single-model mode.
    - If Ollama is unreachable: flags offline mode for deterministic fallback.
    """
    PREFERENCE_FAST = ["qwen2.5:1.5b", "qwen2.5:3b", "qwen2.5:latest", "qwen2.5", "qwen2.5:7b"]
    PREFERENCE_SMART = ["qwen2.5:7b", "qwen2.5:latest", "qwen2.5", "qwen2.5:3b", "qwen2.5:1.5b"]

    def __init__(self):
        self.installed_models = self._fetch_installed_models()
        self.is_offline = len(self.installed_models) == 0

        if self.is_offline:
            logger.warning("[ROUTER] Ollama unreachable or no models found. Offline mode ready.")
            self.stage1_model = "offline"
            self.stage2_model = "offline"
        elif len(self.installed_models) == 1:
            # Single-model laptop guarantee
            only_model = self.installed_models[0]
            self.stage1_model = only_model
            self.stage2_model = only_model
            logger.info(f"[ROUTER] Single model detected ('{only_model}'). Unified Single-Model Mode active.")
        else:
            # Adaptive routing across multiple installed models
            self.stage1_model = self._match_model(self.PREFERENCE_FAST)
            self.stage2_model = self._match_model(self.PREFERENCE_SMART)
            logger.info(f"[ROUTER] Adaptive Routing active -> Stage 1 (Blueprint): {self.stage1_model} | Stage 2 (Matrix): {self.stage2_model}")

    def _fetch_installed_models(self) -> List[str]:
        try:
            res = requests.get(OLLAMA_TAGS_ENDPOINT, timeout=3)
            if res.status_code == 200:
                data = res.json()
                return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception:
            pass
        return []

    def _match_model(self, preferences: List[str]) -> str:
        # 1. Exact match
        for pref in preferences:
            for inst in self.installed_models:
                if pref == inst:
                    return inst
        # 2. Prefix/Substring match (e.g., 'qwen2.5' matches 'qwen2.5:latest')
        for pref in preferences:
            for inst in self.installed_models:
                if pref in inst or inst.startswith(pref):
                    return inst
        # 3. Fallback to whatever is installed
        return self.installed_models[0] if self.installed_models else "qwen2.5"


# =====================================================================
# LOW-LEVEL OLLAMA HTTP CALLER
# =====================================================================

def query_ollama(prompt: str, system_prompt: str = OBE_SYSTEM_PROMPT, model: str = "qwen2.5") -> str:
    """Low-level HTTP caller with JSON formatting and markdown stripping."""
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system_prompt,
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.2,
            "top_p": 0.9,
            "num_predict": 4096
        }
    }
    
    response = requests.post(OLLAMA_GENERATE_ENDPOINT, json=payload, timeout=240)
    
    if response.status_code != 200:
        try:
            err_msg = response.json().get("error", response.text)
        except Exception:
            err_msg = response.text
        raise requests.exceptions.HTTPError(f"Ollama Error ({response.status_code}): {err_msg}", response=response)

    raw_text = response.json().get("response", "").strip()
    
    # Strip markdown if present
    if raw_text.startswith("```json"):
        raw_text = raw_text[7:]
    if raw_text.startswith("```"):
        raw_text = raw_text[3:]
    if raw_text.endswith("```"):
        raw_text = raw_text[:-3]

    return raw_text.strip()


# =====================================================================
# STAGE 1: COURSE BLUEPRINT (METADATA + CLOS + 18 TOPIC TITLES)
# =====================================================================

def generate_stage1_blueprint(
    course_code: str, 
    course_title: str, 
    units: float, 
    description: str, 
    model: str = "qwen2.5", 
    max_retries: int = 3
) -> MacroBlueprintSchema:
    prompt = f"""
Draft an Outcome-Based Education (OBE) Course Blueprint for:
- Course Code: {course_code}
- Title: {course_title}
- Credit Units: {units}
- Description: {description}

REQUIREMENTS:
1. 'course_outcomes': Generate EXACTLY 3 or 4 Course Learning Outcomes (CLO1 to CLO4) with measurable Bloom verbs.
   - bloom_domain: 'Cognitive', 'Psychomotor', or 'Affective'
   - bloom_level: 'Remembering', 'Understanding', 'Applying', 'Analyzing', 'Evaluating', or 'Creating'
2. 'weekly_topic_roadmap': Generate an array of EXACTLY 18 topic strings (Week 1 through Week 18).
   - Week 9 string MUST be: "Midterm Examination and Practical Assessment"
   - Week 18 string MUST be: "Final Examination and Capstone Defense"

JSON Structure:
{{
  "metadata": {{
    "course_code": "{course_code}",
    "course_title": "{course_title}",
    "credit_units": {units},
    "lecture_hours": 2,
    "lab_hours": 3,
    "prerequisites": "None",
    "course_description": "{description}",
    "semester": "1st Semester",
    "academic_year": "2026-2027"
  }},
  "course_outcomes": [
    {{"clo_id": "CLO1", "statement": "Analyze...", "bloom_domain": "Cognitive", "bloom_level": "Analyzing", "po_mapping": ["PO1"]}},
    {{"clo_id": "CLO2", "statement": "Implement...", "bloom_domain": "Psychomotor", "bloom_level": "Applying", "po_mapping": ["PO2"]}},
    {{"clo_id": "CLO3", "statement": "Design...", "bloom_domain": "Cognitive", "bloom_level": "Creating", "po_mapping": ["PO3"]}}
  ],
  "weekly_topic_roadmap": [
    "Orientation and Introduction",
    "Fundamental Concepts",
    ... (18 total items)
  ]
}}
"""
    for attempt in range(1, max_retries + 1):
        logger.info(f"[STAGE 1 ({model})] Generating Blueprint for {course_code} (Attempt {attempt}/{max_retries})...")
        try:
            raw = query_ollama(prompt, model=model)
            data = json.loads(raw)
            blueprint = MacroBlueprintSchema.model_validate(data)
            logger.info(f"[STAGE 1] Blueprint for {course_code} validated successfully!")
            return blueprint
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(f"[STAGE 1] Attempt {attempt} failed: {e}")
            if attempt == max_retries:
                raise e


# =====================================================================
# STAGE 2: 9-WEEK CHUNK GENERATOR (W1-9 OR W10-18)
# =====================================================================

def generate_stage2_chunk(
    blueprint: MacroBlueprintSchema,
    start_week: int,
    end_week: int,
    model: str = "qwen2.5",
    max_retries: int = 3
) -> List[WeeklyScheduleSchema]:
    """Generates and validates a 9-week schedule block with isolated retries."""
    chunk_name = "Midterm (W1-W9)" if start_week == 1 else "Finals (W10-W18)"
    selected_topics = blueprint.weekly_topic_roadmap[start_week - 1 : end_week]
    clos_brief = [{"clo_id": c.clo_id, "statement": c.statement} for c in blueprint.course_outcomes]

    topics_json = json.dumps(
        {f"Week {w}": topic for w, topic in zip(range(start_week, end_week + 1), selected_topics)},
        indent=2
    )

    prompt = f"""
Generate the detailed 9-week OBE Course Schedule for {chunk_name}.
Course: {blueprint.metadata.course_code} - {blueprint.metadata.course_title}
Available CLOs: {json.dumps(clos_brief)}
Topics for this period:
{topics_json}

CRITICAL RULES FOR EVERY WEEK ({start_week} to {end_week}):
1. EVERY week MUST have EXACTLY 3 intended_learning_outcomes:
   - 1 outcome with domain_category = "K" (Knowledge)
   - 1 outcome with domain_category = "S" (Skills)
   - 1 outcome with domain_category = "A" (Attitude)
2. NEVER use 'understand', 'know', or 'learn'. Use active Bloom verbs (Explain, Implement, Evaluate, Adhere, Display).
3. Provide topics, teaching_learning_activities, assessment_tasks, resources_references, and mapped_clos.

JSON format expected:
{{
  "schedules": [
    {{
      "week_number": {start_week},
      "topics": ["..."],
      "intended_learning_outcomes": [
        {{"llo_id": "LLO{start_week}.1", "statement": "Explain...", "domain_category": "K", "bloom_verb": "Explain"}},
        {{"llo_id": "LLO{start_week}.2", "statement": "Implement...", "domain_category": "S", "bloom_verb": "Implement"}},
        {{"llo_id": "LLO{start_week}.3", "statement": "Display...", "domain_category": "A", "bloom_verb": "Display"}}
      ],
      "teaching_learning_activities": ["Lecture", "Hands-on Exercise"],
      "assessment_tasks": ["Quiz", "Machine Problem"],
      "resources_references": ["Textbook Chapter 1"],
      "mapped_clos": ["CLO1"]
    }}
    ... (MUST contain exactly weeks {start_week} through {end_week})
  ]
}}
"""
    for attempt in range(1, max_retries + 1):
        logger.info(f"[STAGE 2 ({model})] Generating {chunk_name} (Attempt {attempt}/{max_retries})...")
        try:
            raw = query_ollama(prompt, model=model)
            data = json.loads(raw)
            chunk = ScheduleChunkSchema.model_validate(data)
            logger.info(f"[STAGE 2] {chunk_name} validated successfully!")
            return chunk.schedules
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(f"[STAGE 2] {chunk_name} Attempt {attempt} failed: {e}")
            if attempt == max_retries:
                raise e


# =====================================================================
# MASTER ORCHESTRATOR (Called by main.py)
# =====================================================================

def generate_validated_syllabus(
    course_code: str,
    course_title: str,
    units: float,
    description: str,
    max_retries: int = 3
) -> FullSyllabusSchema:
    """
    Two-Stage Chunked Orchestrator with Adaptive Model Routing:
    - Queries ModelRouter for best available installed model(s).
    - Stage 1: Macro Blueprint
    - Stage 2A: Midterm Chunk (Weeks 1 to 9)
    - Stage 2B: Finals Chunk (Weeks 10 to 18)
    - Assembly into FullSyllabusSchema
    """
    router = ModelRouter()

    if router.is_offline:
        logger.warning("[PIPELINE] Ollama offline. Generating deterministic offline fallback.")
        return generate_offline_fallback(course_code, course_title, units, description)

    try:
        # Step 1: Macro Blueprint
        blueprint = generate_stage1_blueprint(
            course_code, course_title, units, description,
            model=router.stage1_model, max_retries=max_retries
        )

        # Step 2: Midterm Chunk (Weeks 1-9)
        midterm_weeks = generate_stage2_chunk(
            blueprint, start_week=1, end_week=9,
            model=router.stage2_model, max_retries=max_retries
        )

        # Step 3: Finals Chunk (Weeks 10-18)
        finals_weeks = generate_stage2_chunk(
            blueprint, start_week=10, end_week=18,
            model=router.stage2_model, max_retries=max_retries
        )

        # Step 4: Assembly into full syllabus
        full_payload = {
            "metadata": blueprint.metadata.model_dump(),
            "course_outcomes": [clo.model_dump() for clo in blueprint.course_outcomes],
            "weekly_schedules": [w.model_dump() for w in (midterm_weeks + finals_weeks)]
        }

        validated_syllabus = FullSyllabusSchema.model_validate(full_payload)
        logger.info(f"Two-Stage Syllabus Assembly 100% COMPLETE & VALIDATED for {course_code}!")
        return validated_syllabus

    except requests.exceptions.RequestException as net_err:
        logger.warning(f"Ollama communication error ({net_err}). Switching to deterministic offline fallback.")
        return generate_offline_fallback(course_code, course_title, units, description)


# =====================================================================
# OFFLINE DETERMINISTIC FALLBACK
# =====================================================================

def generate_offline_fallback(course_code: str, course_title: str, units: float, description: str) -> FullSyllabusSchema:
    """Fallback generator for dry-run testing with guaranteed K/S/A completeness."""
    clos = [
        {"clo_id": "CLO1", "statement": f"Analyze fundamental principles, architectures, and theoretical foundations of {course_title}.", "bloom_domain": "Cognitive", "bloom_level": "Analyzing", "po_mapping": ["PO1", "PO2"]},
        {"clo_id": "CLO2", "statement": f"Implement, configure, and evaluate professional computing components for {course_title}.", "bloom_domain": "Psychomotor", "bloom_level": "Applying", "po_mapping": ["PO2", "PO3"]},
        {"clo_id": "CLO3", "statement": f"Design, optimize, and defend scalable systems resolving complex technical challenges in {course_title}.", "bloom_domain": "Cognitive", "bloom_level": "Creating", "po_mapping": ["PO3", "PO8"]},
        {"clo_id": "CLO4", "statement": "Demonstrate professional responsibility, ethical decorum, and team collaboration.", "bloom_domain": "Affective", "bloom_level": "Applying", "po_mapping": ["PO8"]}
    ]

    weekly = []
    for week_num in range(1, 19):
        if week_num == 9:
            w_topics = ["Midterm Examination: Theoretical and Practical Coding Evaluation"]
            llos = [
                {"llo_id": "LLO9.1", "statement": "Integrate theoretical concepts and core algorithms under exam conditions.", "domain_category": "K", "bloom_verb": "Integrate"},
                {"llo_id": "LLO9.2", "statement": "Solve complex timed programming challenges adhering to specifications.", "domain_category": "S", "bloom_verb": "Solve"},
                {"llo_id": "LLO9.3", "statement": "Adhere strictly to institutional academic honesty and testing protocols.", "domain_category": "A", "bloom_verb": "Adhere"}
            ]
        elif week_num == 18:
            w_topics = ["Final Examination and Capstone Project Presentation"]
            llos = [
                {"llo_id": "LLO18.1", "statement": "Synthesize full semester competencies and architectural tradeoffs.", "domain_category": "K", "bloom_verb": "Synthesize"},
                {"llo_id": "LLO18.2", "statement": "Defend system implementation and project findings before the panel.", "domain_category": "S", "bloom_verb": "Defend"},
                {"llo_id": "LLO18.3", "statement": "Display ethical composure and professional communication during oral defense.", "domain_category": "A", "bloom_verb": "Display"}
            ]
        else:
            w_topics = [f"Module {week_num}: Advanced Core Principles of {course_title}"]
            llos = [
                {"llo_id": f"LLO{week_num}.1", "statement": f"Explain key theoretical foundations and design models for Module {week_num}.", "domain_category": "K", "bloom_verb": "Explain"},
                {"llo_id": f"LLO{week_num}.2", "statement": f"Implement practical exercises and algorithmic scripts for Module {week_num}.", "domain_category": "S", "bloom_verb": "Implement"},
                {"llo_id": f"LLO{week_num}.3", "statement": "Demonstrate meticulous attention to code quality and error handling.", "domain_category": "A", "bloom_verb": "Demonstrate"}
            ]

        weekly.append({
            "week_number": week_num,
            "topics": w_topics,
            "intended_learning_outcomes": llos,
            "teaching_learning_activities": ["Interactive Lecture", "Hands-on Programming Lab"],
            "assessment_tasks": [f"Formative Assessment {week_num}", f"Machine Problem {week_num}"],
            "resources_references": ["Official Course Textbooks and Institutional Library Resources"],
            "mapped_clos": ["CLO1" if week_num < 10 else "CLO3"]
        })

    payload = {
        "metadata": {
            "course_code": course_code,
            "course_title": course_title,
            "credit_units": units,
            "lecture_hours": 2,
            "lab_hours": 3,
            "prerequisites": "None",
            "course_description": description,
            "semester": "1st Semester",
            "academic_year": "2026-2027"
        },
        "course_outcomes": clos,
        "weekly_schedules": weekly
    }

    return FullSyllabusSchema.model_validate(payload)