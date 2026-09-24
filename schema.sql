-- ====================================================================
-- College of Computer Studies (CCS) OBE Syllabus Database Schema
-- File: schema.sql
-- Enforces 3NF Normalization, Foreign Key Cascades, and K/S/A Constraints
-- ====================================================================

PRAGMA foreign_keys = ON;

-- 1. Courses Table
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code TEXT UNIQUE NOT NULL,
    course_title TEXT NOT NULL,
    credit_units REAL NOT NULL CHECK(credit_units > 0),
    lecture_hours INTEGER NOT NULL DEFAULT 0,
    lab_hours INTEGER NOT NULL DEFAULT 0,
    prerequisites TEXT NOT NULL DEFAULT 'None',
    course_description TEXT NOT NULL,
    semester TEXT NOT NULL,
    academic_year TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Course Outcomes (CLOs) Table
CREATE TABLE IF NOT EXISTS course_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    clo_id TEXT NOT NULL,
    statement TEXT NOT NULL,
    bloom_domain TEXT NOT NULL,
    bloom_level TEXT NOT NULL,
    po_mapping TEXT NOT NULL, -- Stored as JSON array string: '["PO1", "PO2"]'
    FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
);

-- 3. Weekly Schedules Table
CREATE TABLE IF NOT EXISTS weekly_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    week_number INTEGER NOT NULL CHECK(week_number BETWEEN 1 AND 18),
    topics TEXT NOT NULL, -- JSON array of topics
    tlas TEXT NOT NULL,   -- JSON array of Teaching Learning Activities
    ats TEXT NOT NULL,    -- JSON array of Assessment Tasks
    resources TEXT NOT NULL, -- JSON array of references/resources
    mapped_clos TEXT NOT NULL, -- JSON array of mapped CLO IDs
    FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE,
    UNIQUE(course_id, week_number)
);

-- 4. Lesson Learning Outcomes (LLOs) Table (Explicit K/S/A Partitioning)
CREATE TABLE IF NOT EXISTS lesson_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id INTEGER NOT NULL,
    llo_id TEXT NOT NULL,
    statement TEXT NOT NULL,
    domain_category TEXT CHECK (domain_category IN ('K', 'S', 'A')) NOT NULL,
    bloom_verb TEXT NOT NULL,
    FOREIGN KEY(schedule_id) REFERENCES weekly_schedules(id) ON DELETE CASCADE
);

-- Indexes for rapid retrieval during rendering and updates
CREATE INDEX IF NOT EXISTS idx_courses_code ON courses(course_code);
CREATE INDEX IF NOT EXISTS idx_co_course ON course_outcomes(course_id);
CREATE INDEX IF NOT EXISTS idx_ws_course ON weekly_schedules(course_id);
CREATE INDEX IF NOT EXISTS idx_llo_sched ON lesson_outcomes(schedule_id);