"""SQLite setup, schema initialization, and CRUD helpers."""
import json
import os
import sqlite3

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    source TEXT NOT NULL,
    url TEXT,
    description TEXT,
    date_posted TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER UNIQUE NOT NULL,
    match_score REAL NOT NULL CHECK(match_score BETWEEN 0 AND 10),
    role_fit_summary TEXT,
    key_requirements TEXT,   -- JSON array
    missing_skills TEXT,     -- JSON array
    eval_status TEXT CHECK(eval_status IN ('PASS', 'FAIL', 'BORDERLINE')),
    raw_json TEXT,
    evaluated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_evals_score ON evaluations(match_score);
"""
# Note: external_id and job_id are UNIQUE, so SQLite already indexes them.


def get_connection(path: str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with dict-like rows and foreign keys enabled."""
    path = path or config.db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # required for ON DELETE CASCADE
    return conn


def init_db() -> None:
    """Create the tables and indexes if they don't exist (safe to run repeatedly)."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)


def insert_job(conn: sqlite3.Connection, job: dict) -> bool:
    """Insert a job; returns False if external_id already exists (dedup)."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO jobs
            (external_id, title, company, location, source, url, description, date_posted)
        VALUES (:external_id, :title, :company, :location, :source, :url, :description, :date_posted)
        """,
        job,
    )
    return cur.rowcount == 1


def get_unevaluated_jobs(limit: int | None = None) -> list[sqlite3.Row]:
    """Return jobs that have a description but no evaluation yet, oldest first."""
    sql = """
        SELECT j.* FROM jobs j
        LEFT JOIN evaluations e ON e.job_id = j.id
        WHERE e.id IS NULL AND j.description IS NOT NULL AND j.description != ''
        ORDER BY j.created_at
    """
    params: tuple = ()
    if limit:
        sql += " LIMIT ?"
        params = (limit,)
    with get_connection() as conn:
        return conn.execute(sql, params).fetchall()


def save_evaluation(job_id: int, evaluation: dict, raw_json: str) -> None:
    """Insert or replace the evaluation for a job (re-evaluation overwrites)."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO evaluations
                (job_id, match_score, role_fit_summary, key_requirements,
                 missing_skills, eval_status, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                match_score = excluded.match_score,
                role_fit_summary = excluded.role_fit_summary,
                key_requirements = excluded.key_requirements,
                missing_skills = excluded.missing_skills,
                eval_status = excluded.eval_status,
                raw_json = excluded.raw_json,
                evaluated_at = CURRENT_TIMESTAMP
            """,
            (
                job_id,
                evaluation["match_score"],
                evaluation["role_fit_summary"],
                json.dumps(evaluation["key_requirements"]),
                json.dumps(evaluation["missing_skills"]),
                evaluation["eval_status"],
                raw_json,
            ),
        )


def get_job_with_evaluation(job_id: int) -> sqlite3.Row | None:
    """Return one job joined with its evaluation (evaluation fields are None if not scored)."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT j.*, e.match_score, e.eval_status, e.role_fit_summary,
                   e.key_requirements, e.missing_skills, e.evaluated_at
            FROM jobs j LEFT JOIN evaluations e ON e.job_id = j.id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()


if __name__ == "__main__":
    init_db()
    print(f"Database schema initialized at {config.db_path()}")
