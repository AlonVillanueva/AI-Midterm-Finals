"""
db_manager.py
Database Management Engine for OBE Syllabus Persistence and Faculty CRUD Modifications.
"""

import sqlite3
import json
import os
from typing import Dict, Any, List, Optional
from obe_schemas import FullSyllabusSchema

DB_FILE = "obe_syllabus.db"
SCHEMA_FILE = "schema.sql"


class DatabaseManager:
    def __init__(self, db_path: str = DB_FILE, schema_path: str = SCHEMA_FILE):
        self.db_path = db_path
        self.schema_path = schema_path
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Returns SQLite connection with active Foreign Key enforcement."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Initializes tables using schema.sql."""
        if not os.path.exists(self.schema_path):
            raise FileNotFoundError(f"Schema definition file '{self.schema_path}' not found.")
        
        with open(self.schema_path, "r", encoding="utf-8") as f:
            ddl_script = f.read()

        with self.get_connection() as conn:
            conn.executescript(ddl_script)

    def save_syllabus(self, syllabus: FullSyllabusSchema) -> int:
        """
        Persists a full syllabus transactionally. Replaces existing course if code matches.
        """
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                meta = syllabus.metadata

                # Check if course exists; delete old record to trigger CASCADE
                cursor.execute("SELECT id FROM courses WHERE course_code = ?", (meta.course_code,))
                row = cursor.fetchone()
                if row:
                    cursor.execute("DELETE FROM courses WHERE id = ?", (row["id"],))

                # 1. Insert course metadata
                cursor.execute("""
                    INSERT INTO courses (
                        course_code, course_title, credit_units, lecture_hours, 
                        lab_hours, prerequisites, course_description, semester, academic_year
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    meta.course_code, meta.course_title, meta.credit_units,
                    meta.lecture_hours, meta.lab_hours, meta.prerequisites,
                    meta.course_description, meta.semester, meta.academic_year
                ))
                course_id = cursor.lastrowid

                # 2. Insert Course Learning Outcomes (CLOs)
                for clo in syllabus.course_outcomes:
                    cursor.execute("""
                        INSERT INTO course_outcomes (course_id, clo_id, statement, bloom_domain, bloom_level, po_mapping)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        course_id, clo.clo_id, clo.statement, clo.bloom_domain,
                        clo.bloom_level, json.dumps(clo.po_mapping)
                    ))

                # 3. Insert Weekly Schedules & Linked Lesson Outcomes (LLOs)
                for week in syllabus.weekly_schedules:
                    cursor.execute("""
                        INSERT INTO weekly_schedules (
                            course_id, week_number, topics, tlas, ats, resources, mapped_clos
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        course_id, week.week_number,
                        json.dumps(week.topics),
                        json.dumps(week.teaching_learning_activities),
                        json.dumps(week.assessment_tasks),
                        json.dumps(week.resources_references),
                        json.dumps(week.mapped_clos)
                    ))
                    schedule_id = cursor.lastrowid

                    # 4. Insert LLOs
                    for llo in week.intended_learning_outcomes:
                        cursor.execute("""
                            INSERT INTO lesson_outcomes (schedule_id, llo_id, statement, domain_category, bloom_verb)
                            VALUES (?, ?, ?, ?, ?)
                        """, (
                            schedule_id, llo.llo_id, llo.statement, llo.domain_category, llo.bloom_verb
                        ))

            return course_id

        finally:
            conn.close()

    def get_syllabus(self, course_code: str) -> Optional[Dict[str, Any]]:
        """
        Fetches complete nested syllabus structure from normalized relational tables.
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM courses WHERE course_code = ?", (course_code,))
            course_row = cursor.fetchone()
            if not course_row:
                return None

            course_id = course_row["id"]
            syllabus_dict = {
                "metadata": dict(course_row),
                "course_outcomes": [],
                "weekly_schedules": []
            }

            # Fetch CLOs
            cursor.execute("SELECT * FROM course_outcomes WHERE course_id = ? ORDER BY clo_id", (course_id,))
            for r in cursor.fetchall():
                clo_dict = dict(r)
                clo_dict["po_mapping"] = json.loads(clo_dict["po_mapping"])
                syllabus_dict["course_outcomes"].append(clo_dict)

            # Fetch Weekly Schedules
            cursor.execute("SELECT * FROM weekly_schedules WHERE course_id = ? ORDER BY week_number", (course_id,))
            schedule_rows = cursor.fetchall()

            for s_row in schedule_rows:
                sched_dict = dict(s_row)
                sched_dict["topics"] = json.loads(sched_dict["topics"])
                sched_dict["tlas"] = json.loads(sched_dict["tlas"])
                sched_dict["ats"] = json.loads(sched_dict["ats"])
                sched_dict["resources"] = json.loads(sched_dict["resources"])
                sched_dict["mapped_clos"] = json.loads(sched_dict["mapped_clos"])

                # Fetch LLOs for this week
                cursor.execute("SELECT * FROM lesson_outcomes WHERE schedule_id = ? ORDER BY llo_id", (sched_dict["id"],))
                sched_dict["intended_learning_outcomes"] = [dict(llo) for llo in cursor.fetchall()]

                syllabus_dict["weekly_schedules"].append(sched_dict)

            return syllabus_dict

        finally:
            conn.close()

    def update_course_outcome(self, course_code: str, clo_id: str, new_statement: str, new_bloom_level: Optional[str] = None) -> bool:
        """
        Faculty Human-in-the-Loop CRUD modification for a specific CLO.
        """
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM courses WHERE course_code = ?", (course_code,))
                c_row = cursor.fetchone()
                if not c_row:
                    return False
                course_id = c_row["id"]

                if new_bloom_level:
                    cursor.execute("""
                        UPDATE course_outcomes 
                        SET statement = ?, bloom_level = ?
                        WHERE course_id = ? AND clo_id = ?
                    """, (new_statement, new_bloom_level, course_id, clo_id))
                else:
                    cursor.execute("""
                        UPDATE course_outcomes 
                        SET statement = ?
                        WHERE course_id = ? AND clo_id = ?
                    """, (new_statement, course_id, clo_id))

                return cursor.rowcount > 0
        finally:
            conn.close()

    def update_weekly_topics(self, course_code: str, week_number: int, new_topics: List[str]) -> bool:
        """Faculty CRUD edit for weekly schedule topics."""
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM courses WHERE course_code = ?", (course_code,))
                c_row = cursor.fetchone()
                if not c_row:
                    return False
                course_id = c_row["id"]

                cursor.execute("""
                    UPDATE weekly_schedules
                    SET topics = ?
                    WHERE course_id = ? AND week_number = ?
                """, (json.dumps(new_topics), course_id, week_number))
                return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_syllabus(self, course_code: str) -> bool:
        """Deletes course; cascading delete purges all CLOs, weeks, and LLOs."""
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM courses WHERE course_code = ?", (course_code,))
                return cursor.rowcount > 0
        finally:
            conn.close()

    def list_all_courses(self) -> List[Dict[str, Any]]:
        """Lists all persisted courses in the database."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT course_code, course_title, credit_units, academic_year, semester FROM courses")
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()