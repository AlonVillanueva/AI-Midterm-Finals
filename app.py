"""
app.py
Streamlit Web Dashboard for the UPHSD CCS OBE Syllabus Generator.
Features: Subject selection, Human-in-the-Loop CRUD, Surgical Week Regeneration, and Live HTML Export.
"""

import os
import json
import time
import re
import streamlit as st
import streamlit.components.v1 as components

# Import existing backend modules (zero modifications required)
from main import BSCS_3RD_YEAR_SCHEDULE
from db_manager import DatabaseManager
from export_engine import SyllabusExportEngine
from llm_engine import generate_validated_syllabus, query_ollama, ModelRouter
from obe_schemas import WeeklyScheduleSchema

# Initialize Backend Services
db = DatabaseManager()
exporter = SyllabusExportEngine(db)
router = ModelRouter()

# =====================================================================
# STREAMLIT PAGE CONFIG & UPHSD BRANDING
# =====================================================================
st.set_page_config(
    page_title="UPHSD CCS - OBE Syllabus Generator",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for UPHSD Maroon & Gold Theme
st.markdown("""
<style>
    :root {
        --uphsd-maroon: #7A0019;
        --uphsd-gold: #FFB81C;
    }
    .main-header {
        background: linear-gradient(135deg, #7A0019 0%, #4A000F 100%);
        color: white;
        padding: 20px 25px;
        border-radius: 8px;
        border-bottom: 5px solid #FFB81C;
        margin-bottom: 20px;
    }
    .main-header h1 {
        color: white;
        font-size: 24pt;
        margin: 0;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .main-header p {
        color: #FFB81C;
        margin: 5px 0 0 0;
        font-size: 11pt;
        font-weight: 500;
    }
    .badge-k { background-color: #004085; color: white; padding: 2px 7px; border-radius: 4px; font-weight: bold; font-size: 8.5pt; }
    .badge-s { background-color: #155724; color: white; padding: 2px 7px; border-radius: 4px; font-weight: bold; font-size: 8.5pt; }
    .badge-a { background-color: #856404; color: white; padding: 2px 7px; border-radius: 4px; font-weight: bold; font-size: 8.5pt; }
    .week-card { border-left: 4px solid #7A0019; padding-left: 10px; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)


# =====================================================================
# HELPER: SURGICAL SINGLE-WEEK REGENERATION
# =====================================================================
def regenerate_single_week_in_db(course_code: str, week_num: int, clos: list, current_topic: str) -> bool:
    """
    Surgically re-prompts Ollama for ONLY ONE specific week and updates SQLite directly.
    Finishes in ~3-5 seconds without touching the rest of the syllabus.
    """
    clos_brief = [{"clo_id": c["clo_id"], "statement": c["statement"]} for c in clos]
    is_exam = week_num in [9, 18]
    exam_label = "Midterm Examination" if week_num == 9 else "Final Examination"

    prompt = f"""
    Regenerate ONLY Week {week_num} for course {course_code}.
    Topic context: {"Institutional " + exam_label if is_exam else current_topic}
    Available CLOs: {json.dumps(clos_brief)}

    REQUIREMENTS:
    1. Must contain EXACTLY 3 intended_learning_outcomes:
       - 1 with domain_category = 'K'
       - 1 with domain_category = 'S'
       - 1 with domain_category = 'A'
    2. Active Bloom verbs only. Never use 'understand'.
    3. Return valid JSON matching:
    {{
      "week_number": {week_num},
      "topics": ["{exam_label if is_exam else current_topic}"],
      "intended_learning_outcomes": [
        {{"llo_id": "LLO{week_num}.1", "statement": "Explain...", "domain_category": "K", "bloom_verb": "Explain"}},
        {{"llo_id": "LLO{week_num}.2", "statement": "Implement...", "domain_category": "S", "bloom_verb": "Implement"}},
        {{"llo_id": "LLO{week_num}.3", "statement": "Display...", "domain_category": "A", "bloom_verb": "Display"}}
      ],
      "teaching_learning_activities": ["Interactive Lecture", "Lab Exercise"],
      "assessment_tasks": ["Quiz", "Machine Problem"],
      "resources_references": ["Official Course Materials"],
      "mapped_clos": ["CLO1"]
    }}
    """
    try:
        raw = query_ollama(prompt, model=router.stage2_model)
        parsed = json.loads(raw)
        validated_week = WeeklyScheduleSchema.model_validate(parsed)

        # Atomic SQLite update
        conn = db.get_connection()
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM courses WHERE course_code = ?", (course_code,))
            c_row = cursor.fetchone()
            if not c_row:
                return False
            course_id = c_row["id"]

            cursor.execute("SELECT id FROM weekly_schedules WHERE course_id = ? AND week_number = ?", (course_id, week_num))
            s_row = cursor.fetchone()
            if not s_row:
                return False
            sched_id = s_row["id"]

            # Delete old outcomes for this week
            cursor.execute("DELETE FROM lesson_outcomes WHERE schedule_id = ?", (sched_id,))

            # Update schedule details
            cursor.execute("""
                UPDATE weekly_schedules
                SET topics = ?, tlas = ?, ats = ?, resources = ?, mapped_clos = ?
                WHERE id = ?
            """, (
                json.dumps(validated_week.topics),
                json.dumps(validated_week.teaching_learning_activities),
                json.dumps(validated_week.assessment_tasks),
                json.dumps(validated_week.resources_references),
                json.dumps(validated_week.mapped_clos),
                sched_id
            ))

            # Re-insert fresh LLOs
            for llo in validated_week.intended_learning_outcomes:
                cursor.execute("""
                    INSERT INTO lesson_outcomes (schedule_id, llo_id, statement, domain_category, bloom_verb)
                    VALUES (?, ?, ?, ?, ?)
                """, (sched_id, llo.llo_id, llo.statement, llo.domain_category, llo.bloom_verb))

        return True
    except Exception as err:
        st.error(f"Single-week regeneration error: {err}")
        return False


# =====================================================================
# SIDEBAR: SUBJECT CATALOG & MODEL STATUS
# =====================================================================
with st.sidebar:
    st.image("images/UPHSD-logo 2 smaller.png", width=200)
    st.title("Curriculum Control")

    # 1. Subject Selector
    subject_options = {
        key: f"{c['code']} - {c['title']}" 
        for key, c in BSCS_3RD_YEAR_SCHEDULE.items()
    }
    selected_key = st.selectbox(
        "Select BSCS 3rd Year Course:",
        options=list(subject_options.keys()),
        format_func=lambda k: subject_options[k]
    )
    course_info = BSCS_3RD_YEAR_SCHEDULE[selected_key]

    # Display Subject Metadata Card
    st.markdown(f"""
    **Section:** `{course_info['section']}`  
    **Instructor:** `{course_info['faculty']}`  
    **Units:** `{course_info['units']}` (Lec: {course_info['lec_hours']}h | Lab: {course_info['lab_hours']}h)  
    **Prerequisite:** `{course_info['prereq']}`
    """)

    st.divider()

    # 2. Model Router Diagnostics
    st.markdown("### 🤖 Local AI Engine")
    if router.is_offline:
        st.error("Ollama: Offline (Fallback Mode)")
    else:
        st.success("Ollama: Active")
        st.caption(f"**Stage 1 (Blueprint):** `{router.stage1_model}`")
        st.caption(f"**Stage 2 (Schedule):** `{router.stage2_model}`")

    st.divider()

    # 3. Action Buttons
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        load_btn = st.button("🔄 Reload DB", use_container_width=True)
    with col_btn2:
        regen_all_btn = st.button("⚡ AI Rebuild", type="primary", use_container_width=True)


# =====================================================================
# MAIN HEADER
# =====================================================================
st.markdown(f"""
<div class="main-header">
    <h1>College of Computer Studies</h1>
    <p>Outcome-Based Education (OBE) Course Syllabus Generator | UPHSD Las Piñas</p>
</div>
""", unsafe_allow_html=True)


# =====================================================================
# DATA RETRIEVAL & AI GENERATION ORCHESTRATION
# =====================================================================
syllabus = db.get_syllabus(course_info["code"])

# If user clicked "AI Rebuild" or no record exists yet
if regen_all_btn or (syllabus is None and not load_btn):
    with st.spinner(f"Drafting full 18-week OBE syllabus for {course_info['code']} with {router.stage1_model}..."):
        syllabus_obj = generate_validated_syllabus(
            course_code=course_info["code"],
            course_title=course_info["title"],
            units=course_info["units"],
            description=course_info["description"]
        )
        db.save_syllabus(syllabus_obj)
        syllabus = db.get_syllabus(course_info["code"])
        st.toast(f"✅ {course_info['code']} syllabus persisted to SQLite!", icon="💾")


# If still no syllabus available
if not syllabus:
    st.warning(f"No syllabus found in database for {course_info['code']}. Click '⚡ AI Rebuild' in the sidebar to generate one.")
    st.stop()


# =====================================================================
# DASHBOARD TABS
# =====================================================================
tab_matrix, tab_clos, tab_overview, tab_export = st.tabs([
    "📅 18-Week Course Schedule", 
    "🎯 Course Outcomes (CLO Edit)", 
    "📋 Course Specification",
    "🖨️ Document Export & Print"
])


# ---------------------------------------------------------------------
# TAB 1: 18-WEEK COURSE MATRIX (WITH SURGICAL REGEN BUTTONS)
# ---------------------------------------------------------------------
with tab_matrix:
    st.subheader(f"18-Week Course Design Matrix: {course_info['code']}")
    st.caption("Each week contains verified [K] Knowledge, [S] Skills, and [A] Attitude learning outcomes.")

    for week in syllabus["weekly_schedules"]:
        w_num = week["week_number"]
        is_exam = w_num in [9, 18]
        
        week_title = f"Week {w_num}: {', '.join(week['topics'])}"
        if is_exam:
            week_title = f"⭐ {week_title} (MAJOR ASSESSMENT)"

        with st.expander(week_title, expanded=(w_num in [1, 9, 18])):
            col_l, col_r = st.columns([3, 1])

            with col_l:
                st.markdown("**Intended Learning Outcomes (LLOs):**")
                for llo in week["intended_learning_outcomes"]:
                    badge_class = f"badge-{llo['domain_category'].lower()}"
                    st.markdown(
                        f"<span class='{badge_class}'>[{llo['domain_category']}]</span> "
                        f"<strong>{llo['bloom_verb']}</strong> — {llo['statement']}", 
                        unsafe_allow_html=True
                    )

                st.markdown(f"**Teaching-Learning Activities (TLAs):** {', '.join(week['tlas'])}")
                st.markdown(f"**Assessment Tasks (ATs):** {', '.join(week['ats'])}")
                st.markdown(f"**Mapped Course Outcomes:** `{', '.join(week['mapped_clos'])}`")

            with col_r:
                st.write("")
                st.write("")
                if st.button(f"🔄 Regenerate Week {w_num}", key=f"regen_{w_num}", use_container_width=True):
                    with st.spinner(f"Re-prompting Qwen for Week {w_num}..."):
                        success = regenerate_single_week_in_db(
                            course_code=course_info["code"],
                            week_num=w_num,
                            clos=syllabus["course_outcomes"],
                            current_topic=week["topics"][0]
                        )
                        if success:
                            st.toast(f"Week {w_num} regenerated and updated in SQLite!", icon="🎯")
                            time.sleep(0.5)
                            st.rerun()


# ---------------------------------------------------------------------
# TAB 2: HUMAN-IN-THE-LOOP FACULTY CLO EDITOR
# ---------------------------------------------------------------------
with tab_clos:
    st.subheader("Human-in-the-Loop Faculty Edit Interface")
    st.info("💡 Modify Course Learning Outcomes (CLOs) directly. Clicking Save commits your changes directly to the normalized SQLite database.")

    bloom_levels = ["Remembering", "Understanding", "Applying", "Analyzing", "Evaluating", "Creating"]

    with st.form(key="clo_edit_form"):
        updated_clos = []
        for clo in syllabus["course_outcomes"]:
            st.markdown(f"#### `{clo['clo_id']}` (Mapped to: {', '.join(clo['po_mapping'])})")
            c_col1, c_col2 = st.columns([4, 1])
            with c_col1:
                new_stmt = st.text_area(
                    label=f"Outcome Statement ({clo['clo_id']})", 
                    value=clo["statement"], 
                    height=70,
                    key=f"stmt_{clo['clo_id']}"
                )
            with c_col2:
                current_level_idx = bloom_levels.index(clo["bloom_level"]) if clo["bloom_level"] in bloom_levels else 2
                new_level = st.selectbox(
                    label="Bloom Level", 
                    options=bloom_levels, 
                    index=current_level_idx,
                    key=f"lvl_{clo['clo_id']}"
                )

            updated_clos.append({
                "clo_id": clo["clo_id"],
                "statement": new_stmt,
                "bloom_level": new_level
            })
            st.divider()

        submit_clo = st.form_submit_button("💾 Save Faculty Edits to SQLite", type="primary", use_container_width=True)

        if submit_clo:
            for item in updated_clos:
                db.update_course_outcome(
                    course_code=course_info["code"],
                    clo_id=item["clo_id"],
                    new_statement=item["statement"],
                    new_bloom_level=item["bloom_level"]
                )
            st.success("✅ All Course Outcomes successfully updated in SQLite database!")
            time.sleep(0.6)
            st.rerun()


# ---------------------------------------------------------------------
# TAB 3: COURSE OVERVIEW & SPECIFICATIONS
# ---------------------------------------------------------------------
with tab_overview:
    st.subheader("Course Details & Administrative Specifications")
    meta = syllabus["metadata"]

    o_col1, o_col2 = st.columns(2)
    with o_col1:
        st.text_input("Course Code", value=meta["course_code"], disabled=True)
        st.text_input("Course Title", value=meta["course_title"], disabled=True)
        st.text_input("Assigned Faculty", value=course_info["faculty"], disabled=True)
    with o_col2:
        st.text_input("Credit Units", value=f"{meta['credit_units']} Units", disabled=True)
        st.text_input("Contact Hours", value=f"{meta['lecture_hours']}h Lecture / {meta['lab_hours']}h Lab", disabled=True)
        st.text_input("Academic Term", value=f"{meta['academic_year']} | {meta['semester']}", disabled=True)

    st.text_area("Course Description", value=meta["course_description"], height=120, disabled=True)


# ---------------------------------------------------------------------
# TAB 4: LIVE HTML EXPORT & PRINT PREVIEW
# ---------------------------------------------------------------------
with tab_export:
    st.subheader("Official Institutional Syllabus Preview & Export")

    # Generate current HTML export
    exported_filepath = exporter.render_and_export(course_info["code"], auto_open=False)

    col_exp1, col_exp2 = st.columns([1, 4])
    with col_exp1:
        with open(exported_filepath, "r", encoding="utf-8") as f:
            html_content = f.read()

        st.download_button(
            label="📥 Download HTML Syllabus",
            data=html_content,
            file_name=os.path.basename(exported_filepath),
            mime="text/html",
            use_container_width=True
        )

    with col_exp2:
        st.caption(f"📁 Output file generated: `{os.path.abspath(exported_filepath)}`")
        st.caption("Tip: Open the file in Chrome/Edge and press **Ctrl + P** to save as an official UPHSD PDF.")

    st.divider()

    # Live embedded preview inside Streamlit
    components.html(html_content, height=850, scrolling=True)