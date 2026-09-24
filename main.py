"""
main.py
End-to-End Orchestrator: Generation -> Validation -> Persistence -> CRUD -> Jinja2 HTML Export.
Preloaded with the official 3rd Year BSCS Subject Schedule (AY 2026-2027).
"""

import os
import sys
import json
import time
from obe_schemas import FullSyllabusSchema
from llm_engine import generate_validated_syllabus
from db_manager import DatabaseManager
from export_engine import SyllabusExportEngine


# Official Course Catalog directly extracted from the BSCS Schedule
BSCS_3RD_YEAR_SCHEDULE = {
    "1": {
        "code": "BSCS 3112",
        "title": "Artificial Intelligence",
        "units": 3.0,
        "lec_hours": 3,
        "lab_hours": 0,
        "faculty": "Engr. Rob Malitao",
        "section": "9420-AY126",
        "prereq": "CC104 - Data Structures and Algorithms",
        "description": (
            "A foundational study of artificial intelligence principles, intelligent agents, "
            "uninformed and heuristic search algorithms, adversarial game trees, knowledge representation, "
            "probabilistic reasoning, machine learning fundamentals, and the architectural implementation "
            "of local Large Language Model microservices."
        )
    },
    "2": {
        "code": "BSCS 3108",
        "title": "Automata Theory and Formal Language",
        "units": 3.0,
        "lec_hours": 3,
        "lab_hours": 0,
        "faculty": "Mr. Galve",
        "section": "9413-AY126",
        "prereq": "Discrete Structures 2",
        "description": (
            "Theoretical computation foundations covering deterministic and non-deterministic finite automata (DFA/NFA), "
            "regular expressions, context-free grammars (CFGs), pushdown automata, Turing machines, "
            "decidability, halting problems, and practical compiler lexical/syntactic parsing."
        )
    },
    "3": {
        "code": "BSCS 3109",
        "title": "Operating System Configuration and Use",
        "units": 3.0,
        "lec_hours": 2,
        "lab_hours": 3,
        "faculty": "Ms. Antonio",
        "section": "9414-AY126 / 9415-AY126",
        "prereq": "Computer Organization and Architecture",
        "description": (
            "Core principles of modern operating systems covering process concurrency, thread synchronization, "
            "CPU scheduling algorithms, deadlock handling, virtual memory management, file systems, "
            "and hands-on Linux system administration, shell automation, and POSIX system call programming."
        )
    },
    "4": {
        "code": "BSCS 3110",
        "title": "Information Assurance and Security",
        "units": 3.0,
        "lec_hours": 2,
        "lab_hours": 3,
        "faculty": "Mr. Dacallos",
        "section": "9416-AY126 / 9417-AY126",
        "prereq": "Data Communication and Networking",
        "description": (
            "Comprehensive principles of cyber defense, classical and modern cryptography (AES, RSA), "
            "threat modeling, vulnerability assessment, ethical penetration testing, network access control, "
            "and institutional risk management compliance under ISO/IEC 27001 standards."
        )
    },
    "5": {
        "code": "BSCS 3111",
        "title": "Data Mining",
        "units": 3.0,
        "lec_hours": 2,
        "lab_hours": 3,
        "faculty": "Mr. Dacallos",
        "section": "9418-AY126 / 9419-AY126",
        "prereq": "Advanced Database Systems",
        "description": (
            "Techniques for pattern extraction from high-dimensional datasets: data cleaning, normalization, "
            "association rule discovery (Apriori), decision trees, ensemble methods, clustering (K-Means, DBSCAN), "
            "anomaly detection, and production data science pipeline evaluation."
        )
    },
    "6": {
        "code": "FCL 3105",
        "title": "The Perpetualite: A Filipino Christian Leader",
        "units": 2.0,
        "lec_hours": 2,
        "lab_hours": 0,
        "faculty": "TBA",
        "section": "0744-AY126",
        "prereq": "None",
        "description": (
            "Values-formation curriculum cultivating character building as nation building, ethical leadership, "
            "civic engagement, Christian stewardship, and social responsibility in the digital age."
        )
    },
    "7": {
        "code": "ENG 1000",
        "title": "English for the Profession",
        "units": 3.0,
        "lec_hours": 3,
        "lab_hours": 0,
        "faculty": "TBA",
        "section": "0101-AY126",
        "prereq": "Purposive Communication",
        "description": (
            "Advanced professional communication focusing on executive technical report writing, computing research "
            "manuscript formatting, oral pitching, and collaborative corporate correspondence in software industries."
        )
    }
}


def run_single_subject(course_info: dict, db: DatabaseManager, exporter: SyllabusExportEngine):
    """Executes the pipeline for a single course."""
    code = course_info["code"]
    title = course_info["title"]
    units = course_info["units"]
    desc = course_info["description"]
    faculty = course_info["faculty"]

    print("\n" + "=" * 75)
    print(f"  PROCESSING: {code} - {title} (Faculty: {faculty})")
    print("=" * 75)

    # Step 1: Generate & Validate
    print(f"\n[STEP 1] Generating and Validating OBE Syllabus for {code}...")
    start_time = time.time()
    syllabus_obj = generate_validated_syllabus(code, title, units, desc)
    elapsed = time.time() - start_time
    print(f"Validation 100% PASSED! (Generation Time: {elapsed:.2f}s)")

    # Step 2: Persist in SQLite
    print("\n[STEP 2] Ingesting into SQLite Database (schema.sql)...")
    course_id = db.save_syllabus(syllabus_obj)
    print(f"Ingested successfully with Course Primary Key ID: {course_id}")

    # Step 3: Faculty CRUD Edit
    print("\n[STEP 3] Performing Human-in-the-Loop Faculty Edit...")
    updated_statement = (
        f"Design, optimize, and defend scalable computational solutions for {title} "
        f"adhering to rigorous engineering and quality assurance standards."
    )
    db.update_course_outcome(code, "CLO2", updated_statement, new_bloom_level="Creating")
    print("CLO2 updated in SQLite database.")

    # Step 4: Export to HTML
    print("\n[STEP 4] Compiling Relational Records into Official HTML Syllabus...")
    exported_path = exporter.render_and_export(code, auto_open=True)
    print(f"SUCCESS! Syllabus saved to: {exported_path}")
    return elapsed


def run_batch_benchmark(db: DatabaseManager, exporter: SyllabusExportEngine):
    """Benchmarks generation performance across all 3rd-year subjects."""
    print("\n" + "=" * 75)
    print("  STARTING BATCH GENERATION BENCHMARK ACROSS 3RD YEAR SUBJECTS")
    print("=" * 75)

    results = []
    total_start = time.time()

    for key, course in BSCS_3RD_YEAR_SCHEDULE.items():
        print(f"\n>> Benchmarking [{key}/7]: {course['code']} - {course['title']}...")
        sub_start = time.time()
        syllabus_obj = generate_validated_syllabus(
            course["code"], course["title"], course["units"], course["description"]
        )
        db.save_syllabus(syllabus_obj)
        exporter.render_and_export(course["code"], auto_open=False)
        duration = time.time() - sub_start
        results.append((course["code"], course["title"], duration))

    total_duration = time.time() - total_start

    print("\n" + "=" * 75)
    print("               3RD YEAR SUBJECTS BENCHMARK REPORT")
    print("=" * 75)
    print(f"{'Course Code':<15} {'Course Title':<40} {'Duration (s)':<12}")
    print("-" * 75)
    for code, title, dur in results:
        print(f"{code:<15} {title[:38]:<40} {dur:<12.2f}")
    print("-" * 75)
    print(f"Total Batch Ingestion Time: {total_duration:.2f} seconds")
    print("All 3rd-year syllabi compiled and persisted in SQLite.")
    print("=" * 75)


def main():
    print("=" * 75)
    print("      CCS OBE SYLLABUS GENERATOR - 3RD YEAR BSCS SCHEDULE (AY 2026-2027)")
    print("=" * 75)
    print("Select a subject from your schedule to generate:")
    for key, c in BSCS_3RD_YEAR_SCHEDULE.items():
        print(f"  [{key}] {c['code']} - {c['title']} ({c['faculty']})")
    print("  [8] Run Batch Benchmark across ALL 3rd Year Subjects (Milestone Rubric)")
    print("  [0] Exit")

    choice = input("\nEnter your choice (1-8): ").strip()

    if choice == "0":
        print("Exiting.")
        sys.exit(0)

    db = DatabaseManager()
    exporter = SyllabusExportEngine(db)

    if choice == "8":
        run_batch_benchmark(db, exporter)
    elif choice in BSCS_3RD_YEAR_SCHEDULE:
        run_single_subject(BSCS_3RD_YEAR_SCHEDULE[choice], db, exporter)
    else:
        print("Defaulting to [1] BSCS 3112: Artificial Intelligence...")
        run_single_subject(BSCS_3RD_YEAR_SCHEDULE["1"], db, exporter)


if __name__ == "__main__":
    main()