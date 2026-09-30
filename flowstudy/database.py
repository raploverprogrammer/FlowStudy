from __future__ import annotations

import json
import random
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Iterator

from flowstudy.config import DB_PATH
from flowstudy.content import concept_for_question, get_concepts, get_topic
from flowstudy.knowledge_catalog import catalog_nodes


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column(
    conn: sqlite3.Connection, table: str, name: str, definition: str
) -> None:
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db() -> None:
    """Create V2 tables and add V2 fields to an existing V1 database."""
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS lesson_progress (
                day INTEGER PRIMARY KEY,
                completed INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id TEXT NOT NULL,
                day INTEGER NOT NULL DEFAULT 0,
                knowledge_point TEXT NOT NULL,
                selected_answer TEXT NOT NULL,
                is_correct INTEGER NOT NULL,
                attempted_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS wrong_questions (
                question_id TEXT PRIMARY KEY,
                day INTEGER NOT NULL DEFAULT 0,
                question_text TEXT NOT NULL,
                knowledge_point TEXT NOT NULL,
                wrong_count INTEGER NOT NULL DEFAULT 1,
                last_wrong_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day INTEGER NOT NULL DEFAULT 0,
                duration_seconds INTEGER NOT NULL,
                studied_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS study_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL,
                recorded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS topic_progress (
                topic_id TEXT PRIMARY KEY,
                mastery REAL NOT NULL DEFAULT 0,
                diagnostic_score REAL,
                completed INTEGER NOT NULL DEFAULT 0,
                last_studied_at TEXT,
                next_review_at TEXT
            );

            CREATE TABLE IF NOT EXISTS concept_mastery (
                concept_id TEXT PRIMARY KEY,
                topic_id TEXT NOT NULL,
                concept_name TEXT NOT NULL,
                mastery REAL NOT NULL DEFAULT 0.5,
                attempts INTEGER NOT NULL DEFAULT 0,
                correct_attempts INTEGER NOT NULL DEFAULT 0,
                last_studied_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tutor_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                focus_concept_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                turn_count INTEGER NOT NULL DEFAULT 0,
                summary_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS tutor_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                concept_id TEXT,
                assessment TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES tutor_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS learning_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                content TEXT NOT NULL,
                mastered TEXT NOT NULL DEFAULT '',
                mistakes TEXT NOT NULL DEFAULT '',
                insight TEXT NOT NULL DEFAULT '',
                next_suggestion TEXT NOT NULL DEFAULT '',
                review_focus TEXT NOT NULL DEFAULT '',
                favorited INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES tutor_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS ai_tutor_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                topic_id TEXT NOT NULL,
                concept_id TEXT NOT NULL,
                question TEXT NOT NULL,
                question_json TEXT NOT NULL,
                user_answer TEXT NOT NULL,
                is_correct INTEGER NOT NULL,
                mistake_type TEXT NOT NULL DEFAULT '',
                rating TEXT,
                summary TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES tutor_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS question_bank_sections (
                id TEXT PRIMARY KEY,
                batch INTEGER NOT NULL,
                phase TEXT NOT NULL,
                subject TEXT NOT NULL,
                chapter_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                question_page_start INTEGER NOT NULL,
                question_page_end INTEGER NOT NULL,
                answer_page_start INTEGER NOT NULL,
                answer_page_end INTEGER NOT NULL,
                question_count INTEGER NOT NULL DEFAULT 0,
                verified_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS question_bank (
                id TEXT PRIMARY KEY,
                section_id TEXT NOT NULL,
                question_number INTEGER NOT NULL,
                question_type TEXT NOT NULL,
                question_text TEXT NOT NULL DEFAULT '',
                question_images_json TEXT NOT NULL,
                answer_text TEXT NOT NULL DEFAULT '',
                answer_choice TEXT,
                answer_images_json TEXT NOT NULL DEFAULT '[]',
                auto_gradable INTEGER NOT NULL DEFAULT 0,
                confidence REAL NOT NULL DEFAULT 0,
                review_status TEXT NOT NULL DEFAULT 'needs_review',
                source_question_pages TEXT NOT NULL,
                source_answer_pages TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(section_id) REFERENCES question_bank_sections(id),
                UNIQUE(section_id, question_number)
            );

            CREATE INDEX IF NOT EXISTS idx_question_bank_section
            ON question_bank(section_id, question_number);

            CREATE TABLE IF NOT EXISTS knowledge_nodes (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                chapter_number INTEGER NOT NULL,
                phase TEXT NOT NULL,
                title TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'section_fallback',
                confidence REAL NOT NULL DEFAULT 0.55,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS question_knowledge (
                question_id TEXT NOT NULL,
                knowledge_id TEXT NOT NULL,
                relation TEXT NOT NULL DEFAULT 'primary',
                confidence REAL NOT NULL DEFAULT 0.55,
                source TEXT NOT NULL DEFAULT 'section_fallback',
                PRIMARY KEY(question_id, knowledge_id),
                FOREIGN KEY(question_id) REFERENCES question_bank(id),
                FOREIGN KEY(knowledge_id) REFERENCES knowledge_nodes(id)
            );

            CREATE INDEX IF NOT EXISTS idx_question_knowledge_node
            ON question_knowledge(knowledge_id);

            CREATE TABLE IF NOT EXISTS knowledge_prerequisites (
                knowledge_id TEXT NOT NULL,
                prerequisite_id TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                source TEXT NOT NULL DEFAULT 'curated',
                PRIMARY KEY(knowledge_id, prerequisite_id),
                FOREIGN KEY(knowledge_id) REFERENCES knowledge_nodes(id),
                FOREIGN KEY(prerequisite_id) REFERENCES knowledge_nodes(id)
            );

            CREATE TABLE IF NOT EXISTS daily_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_question_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                context_json TEXT NOT NULL DEFAULT '{}',
                report_json TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS react_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_session_id INTEGER,
                original_question_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                step_count INTEGER NOT NULL DEFAULT 0,
                context_json TEXT NOT NULL DEFAULT '{}',
                report_json TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                FOREIGN KEY(daily_session_id) REFERENCES daily_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS react_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                step_number INTEGER NOT NULL,
                action TEXT NOT NULL,
                observation_json TEXT NOT NULL DEFAULT '{}',
                tool_name TEXT NOT NULL DEFAULT '',
                tool_input_json TEXT NOT NULL DEFAULT '{}',
                tool_output_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES react_runs(id)
            );
            """
        )

        for table, fields in {
            "quiz_attempts": {
                "topic_id": "TEXT",
                "attempt_type": "TEXT NOT NULL DEFAULT 'practice'",
                "question_json": "TEXT",
            },
            "wrong_questions": {
                "topic_id": "TEXT",
                "question_json": "TEXT",
                "last_selected_answer": "TEXT",
                "resolved": "INTEGER NOT NULL DEFAULT 0",
            },
            "tutor_sessions": {
                "context_json": "TEXT NOT NULL DEFAULT '{}'",
                "rating": "TEXT",
                "correct_count": "INTEGER NOT NULL DEFAULT 0",
            },
            "learning_summaries": {
                "rating": "TEXT",
                "question_images_json": "TEXT NOT NULL DEFAULT '[]'",
            },
            "question_bank_sections": {
                "source": "TEXT NOT NULL DEFAULT 'zhangyu1000'",
                "source_label": "TEXT NOT NULL DEFAULT '张宇1000题'",
            },
            "question_bank": {
                "source_question_label": "TEXT NOT NULL DEFAULT ''",
            },
        }.items():
            for name, definition in fields.items():
                _add_column(conn, table, name, definition)
        _seed_concept_mastery(conn)
        _seed_knowledge_catalog(conn)
        _seed_question_knowledge(conn)
        current_ids = {concept["id"] for concept in get_concepts()}
        placeholders = ",".join("?" for _ in current_ids)
        conn.execute(
            f"""
            UPDATE tutor_sessions
            SET status = 'abandoned', ended_at = ?
            WHERE status = 'active'
              AND focus_concept_id NOT IN ({placeholders})
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                *sorted(current_ids),
            ),
        )


def _seed_question_knowledge(conn: sqlite3.Connection) -> None:
    """Attach every imported question to a reliable section-level concept.

    OCR quality varies across the scanned books, so the first tagging pass uses
    the importer-owned subject/chapter/phase metadata as a safe fallback. More
    specific tags can be added later without changing the question bank.
    """
    now = datetime.now().isoformat(timespec="seconds")
    sections = conn.execute(
        """
        SELECT id, subject, chapter_number, phase, title, source
        FROM question_bank_sections
        """
    ).fetchall()
    for section in sections:
        knowledge_id = f"section:{section['id']}"
        conn.execute(
            """
            INSERT INTO knowledge_nodes(
                id, subject, chapter_number, phase, title,
                source, confidence, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'section_fallback', 0.55, ?)
            ON CONFLICT(id) DO UPDATE SET
                subject = excluded.subject,
                chapter_number = excluded.chapter_number,
                phase = excluded.phase,
                title = excluded.title,
                updated_at = excluded.updated_at
            """,
            (
                knowledge_id,
                section["subject"],
                section["chapter_number"],
                section["phase"],
                section["title"],
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO question_knowledge(
                question_id, knowledge_id, relation, confidence, source
            )
            SELECT id, ?, 'primary', 0.55, 'section_fallback'
            FROM question_bank
            WHERE section_id = ?
            """,
            (knowledge_id, section["id"]),
        )


def _seed_knowledge_catalog(conn: sqlite3.Connection) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    nodes = catalog_nodes()
    for node in nodes:
        conn.execute(
            """
            INSERT INTO knowledge_nodes(
                id, subject, chapter_number, phase, title,
                source, confidence, updated_at
            ) VALUES (?, ?, ?, 'catalog', ?, 'curated', 1.0, ?)
            ON CONFLICT(id) DO UPDATE SET
                subject = excluded.subject,
                chapter_number = excluded.chapter_number,
                title = excluded.title,
                source = 'curated',
                confidence = 1.0,
                updated_at = excluded.updated_at
            """,
            (
                node["id"],
                node["subject"],
                node["chapter_number"],
                node["title"],
                now,
            ),
        )
    for node in nodes:
        for prerequisite_id in node["prerequisites"]:
            conn.execute(
                """
                INSERT OR REPLACE INTO knowledge_prerequisites(
                    knowledge_id, prerequisite_id, confidence, source
                ) VALUES (?, ?, 1.0, 'curated')
                """,
                (node["id"], prerequisite_id),
            )


def _seed_concept_mastery(conn: sqlite3.Connection) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    topic_rows = {
        row["topic_id"]: float(row["mastery"])
        for row in conn.execute("SELECT topic_id, mastery FROM topic_progress")
    }
    for concept in get_concepts():
        initial = topic_rows.get(concept["topic_id"], 0.5)
        conn.execute(
            """
            INSERT OR IGNORE INTO concept_mastery(
                concept_id, topic_id, concept_name, mastery, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                concept["id"],
                concept["topic_id"],
                concept["concept"],
                initial,
                now,
            ),
        )
    legacy_prefixes = {
        "chapter-1": "l1-%",
        "chapter-2": "l2-%",
        "chapter-3": "l3-%",
        "chapter-4": "l4-%",
        "chapter-5": "l5-%",
        "chapter-6": "l6-%",
    }
    for chapter_id, pattern in legacy_prefixes.items():
        chapter = conn.execute(
            "SELECT attempts FROM concept_mastery WHERE concept_id = ?",
            (chapter_id,),
        ).fetchone()
        if not chapter or int(chapter["attempts"]) > 0:
            continue
        legacy = conn.execute(
            """
            SELECT COALESCE(SUM(attempts), 0) AS attempts,
                   COALESCE(SUM(correct_attempts), 0) AS correct_attempts,
                   MAX(last_studied_at) AS last_studied_at
            FROM concept_mastery
            WHERE concept_id LIKE ?
            """,
            (pattern,),
        ).fetchone()
        attempts = int(legacy["attempts"])
        correct = int(legacy["correct_attempts"])
        if attempts:
            conn.execute(
                """
                UPDATE concept_mastery
                SET mastery = ?, attempts = ?, correct_attempts = ?,
                    last_studied_at = ?, updated_at = ?
                WHERE concept_id = ?
                """,
                (
                    correct / attempts,
                    attempts,
                    correct,
                    legacy["last_studied_at"],
                    now,
                    chapter_id,
                ),
            )


def record_activity(topic_id: str, duration_seconds: int) -> None:
    if duration_seconds <= 0:
        return
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO study_activity(topic_id, duration_seconds, recorded_at)
            VALUES (?, ?, ?)
            """,
            (topic_id, duration_seconds, datetime.now().isoformat(timespec="seconds")),
        )


def record_attempt(
    question: dict[str, Any],
    topic_id: str,
    selected: list[int],
    is_correct: bool,
    attempt_type: str = "practice",
    update_mastery: bool = True,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    question_json = json.dumps(question, ensure_ascii=False)
    selected_json = json.dumps(selected)
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO quiz_attempts(
                question_id, day, knowledge_point, selected_answer,
                is_correct, attempted_at, topic_id, attempt_type, question_json
            ) VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question["id"],
                question["knowledge_point"],
                selected_json,
                int(is_correct),
                now,
                topic_id,
                attempt_type,
                question_json,
            ),
        )
        if not is_correct:
            conn.execute(
                """
                INSERT INTO wrong_questions(
                    question_id, day, question_text, knowledge_point,
                    wrong_count, last_wrong_at, topic_id, question_json,
                    last_selected_answer, resolved
                ) VALUES (?, 0, ?, ?, 1, ?, ?, ?, ?, 0)
                ON CONFLICT(question_id) DO UPDATE SET
                    wrong_count = wrong_count + 1,
                    last_wrong_at = excluded.last_wrong_at,
                    topic_id = excluded.topic_id,
                    question_json = excluded.question_json,
                    last_selected_answer = excluded.last_selected_answer,
                    resolved = 0
                """,
                (
                    question["id"],
                    question["question"],
                    question["knowledge_point"],
                    now,
                    topic_id,
                    question_json,
                    selected_json,
                ),
            )
        if update_mastery:
            try:
                concept = concept_for_question(get_topic(topic_id), question)
                _update_concept_mastery_in_connection(
                    conn, concept["id"], is_correct, 1.0 if is_correct else 0.0
                )
            except KeyError:
                pass


def _update_concept_mastery_in_connection(
    conn: sqlite3.Connection,
    concept_key: str,
    is_correct: bool,
    quality: float,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    row = conn.execute(
        "SELECT mastery, attempts FROM concept_mastery WHERE concept_id = ?",
        (concept_key,),
    ).fetchone()
    if not row:
        return
    attempts = int(row["attempts"])
    correct_row = conn.execute(
        "SELECT correct_attempts FROM concept_mastery WHERE concept_id = ?",
        (concept_key,),
    ).fetchone()
    correct_attempts = int(correct_row["correct_attempts"]) if correct_row else 0
    updated = (correct_attempts + int(is_correct)) / (attempts + 1)
    conn.execute(
        """
        UPDATE concept_mastery
        SET mastery = ?, attempts = attempts + 1,
            correct_attempts = correct_attempts + ?,
            last_studied_at = ?, updated_at = ?
        WHERE concept_id = ?
        """,
        (updated, int(is_correct), now, now, concept_key),
    )


def update_concept_mastery(
    concept_key: str, assessment: str
) -> float:
    quality = {"correct": 1.0, "partial": 0.55, "incorrect": 0.0}.get(
        assessment, 0.4
    )
    with connection() as conn:
        _update_concept_mastery_in_connection(
            conn, concept_key, assessment == "correct", quality
        )
        row = conn.execute(
            "SELECT mastery FROM concept_mastery WHERE concept_id = ?",
            (concept_key,),
        ).fetchone()
    return float(row["mastery"]) if row else 0.5


def get_concept_mastery() -> dict[str, sqlite3.Row]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM concept_mastery ORDER BY mastery, updated_at"
        ).fetchall()
    return {row["concept_id"]: row for row in rows}


def mastery_level(mastery: float) -> dict[str, str]:
    value = max(0.0, min(1.0, mastery))
    if value < 0.2:
        return {"key": "seed", "emoji": "🌱", "name": "萌芽"}
    if value < 0.5:
        return {"key": "growing", "emoji": "🌿", "name": "成长"}
    if value < 0.8:
        return {"key": "skilled", "emoji": "🌳", "name": "熟练"}
    return {"key": "mastered", "emoji": "⭐", "name": "精通"}


def get_growth_overview() -> dict[str, Any]:
    """Return effective mastery; unseen concepts count as 0 instead of seed 0.5."""
    catalog = get_concepts()
    current_ids = {item["id"] for item in catalog}
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT concept_id, mastery, attempts
            FROM concept_mastery
            """
        ).fetchall()
    values = {
        row["concept_id"]: (
            float(row["mastery"]) if int(row["attempts"]) > 0 else 0.0
        )
        for row in rows
        if row["concept_id"] in current_ids
    }
    distribution = {
        "seed": 0,
        "growing": 0,
        "skilled": 0,
        "mastered": 0,
    }
    for concept in catalog:
        level = mastery_level(values.get(concept["id"], 0.0))
        distribution[level["key"]] += 1
    overall = (
        sum(values.get(concept["id"], 0.0) for concept in catalog) / len(catalog)
        if catalog
        else 0.0
    )
    return {
        "overall": overall,
        "distribution": distribution,
        "concept_count": len(catalog),
        "lit_chapters": sum(
            int(row["attempts"]) > 0
            for row in rows
            if row["concept_id"] in current_ids
        ),
    }


def get_weak_concepts(limit: int = 5) -> list[dict[str, Any]]:
    """Rank weaknesses from mastery, wrong questions and recent performance."""
    concept_catalog = {item["id"]: item for item in get_concepts()}
    with connection() as conn:
        mastery_rows = conn.execute("SELECT * FROM concept_mastery").fetchall()
        wrong_rows = conn.execute(
            """
            SELECT topic_id, knowledge_point, SUM(wrong_count) AS wrong_count,
                   MAX(last_wrong_at) AS last_wrong_at
            FROM wrong_questions
            WHERE resolved = 0
            GROUP BY topic_id, knowledge_point
            """
        ).fetchall()
        recent_rows = conn.execute(
            """
            SELECT topic_id, knowledge_point, COUNT(*) AS attempts,
                   AVG(is_correct) AS accuracy, MAX(attempted_at) AS last_attempt
            FROM quiz_attempts
            WHERE attempted_at >= ?
            GROUP BY topic_id, knowledge_point
            """,
            ((datetime.now() - timedelta(days=14)).isoformat(timespec="seconds"),),
        ).fetchall()
        favorite_rows = conn.execute(
            """
            SELECT review_focus, insight
            FROM learning_summaries
            WHERE favorited = 1
            ORDER BY created_at DESC
            LIMIT 10
            """
        ).fetchall()

    evidence: dict[str, dict[str, Any]] = {}
    for row in mastery_rows:
        catalog_item = concept_catalog.get(row["concept_id"])
        if not catalog_item:
            continue
        evidence[row["concept_id"]] = {
            "concept_id": row["concept_id"],
            "topic_id": row["topic_id"],
            "concept": row["concept_name"],
            "topic": catalog_item["topic"],
            "breadcrumb": catalog_item["breadcrumb"],
            "mastery": float(row["mastery"]),
            "wrong_count": 0,
            "recent_attempts": 0,
            "recent_accuracy": None,
            "last_seen": row["last_studied_at"],
            "favorite_mentions": 0,
        }

    def attach(row: sqlite3.Row, kind: str) -> None:
        if not row["topic_id"]:
            return
        if row["topic_id"] in concept_catalog:
            key = row["topic_id"]
        else:
            try:
                topic = get_topic(row["topic_id"])
                fake_question = {"knowledge_point": row["knowledge_point"]}
                key = concept_for_question(topic, fake_question)["id"]
            except KeyError:
                return
        item = evidence.get(key)
        if not item:
            return
        if kind == "wrong":
            item["wrong_count"] += int(row["wrong_count"])
            item["last_seen"] = row["last_wrong_at"]
        else:
            item["recent_attempts"] += int(row["attempts"])
            item["recent_accuracy"] = float(row["accuracy"])
            item["last_seen"] = row["last_attempt"]

    for row in wrong_rows:
        attach(row, "wrong")
    for row in recent_rows:
        attach(row, "recent")
    for row in favorite_rows:
        text = f"{row['review_focus']} {row['insight']}"
        for item in evidence.values():
            if item["concept"] and item["concept"] in text:
                item["favorite_mentions"] += 1

    for item in evidence.values():
        weakness = (1.0 - item["mastery"]) * 60
        weakness += min(item["wrong_count"] * 8, 24)
        if item["recent_accuracy"] is not None:
            weakness += (1.0 - item["recent_accuracy"]) * 16
        if item["recent_attempts"] == 0 and item["wrong_count"] == 0:
            weakness -= 25
        weakness += min(item["favorite_mentions"] * 3, 6)
        item["weakness_score"] = weakness
    return sorted(
        evidence.values(),
        key=lambda item: (
            -item["weakness_score"],
            item["mastery"],
            item["concept"],
        ),
    )[:limit]


def start_tutor_session(concept_key: str) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with connection() as conn:
        conn.execute(
            """
            UPDATE tutor_sessions
            SET status = 'abandoned', ended_at = ?
            WHERE status = 'active'
            """,
            (now,),
        )
        cursor = conn.execute(
            """
            INSERT INTO tutor_sessions(focus_concept_id, started_at)
            VALUES (?, ?)
            """,
            (concept_key, now),
        )
        return int(cursor.lastrowid)


def get_concept_learning_context(concept_key: str) -> dict[str, Any]:
    for item in get_weak_concepts(len(get_concepts())):
        if item["concept_id"] == concept_key:
            return item
    concept = next(item for item in get_concepts() if item["id"] == concept_key)
    mastery = get_concept_mastery().get(concept_key)
    return {
        "concept_id": concept_key,
        "topic_id": concept["topic_id"],
        "topic": concept["topic"],
        "concept": concept["concept"],
        "breadcrumb": concept["breadcrumb"],
        "mastery": float(mastery["mastery"]) if mastery else 0.5,
        "wrong_count": 0,
        "recent_attempts": 0,
        "recent_accuracy": None,
        "last_seen": None,
        "favorite_mentions": 0,
        "weakness_score": 0,
    }


def get_active_tutor_session() -> sqlite3.Row | None:
    with connection() as conn:
        return conn.execute(
            """
            SELECT * FROM tutor_sessions
            WHERE status = 'active'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()


def get_tutor_session(session_id: int) -> sqlite3.Row | None:
    with connection() as conn:
        return conn.execute(
            "SELECT * FROM tutor_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()


def update_tutor_context(session_id: int, context: dict[str, Any]) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE tutor_sessions SET context_json = ? WHERE id = ?",
            (json.dumps(context, ensure_ascii=False), session_id),
        )


def add_tutor_message(
    session_id: int,
    role: str,
    content: str,
    concept_key: str | None = None,
    assessment: str | None = None,
) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO tutor_messages(
                session_id, role, content, concept_id, assessment, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                role,
                content,
                concept_key,
                assessment,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        if role == "user":
            conn.execute(
                "UPDATE tutor_sessions SET turn_count = turn_count + 1 WHERE id = ?",
                (session_id,),
            )


def get_tutor_messages(session_id: int) -> list[sqlite3.Row]:
    with connection() as conn:
        return conn.execute(
            """
            SELECT * FROM tutor_messages
            WHERE session_id = ?
            ORDER BY id
            """,
            (session_id,),
        ).fetchall()


def record_ai_tutor_attempt(
    session_id: int,
    topic_id: str,
    concept_id: str,
    question: dict[str, Any],
    user_answer: str,
    is_correct: bool,
    mistake_type: str,
) -> int:
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO ai_tutor_attempts(
                session_id, topic_id, concept_id, question, question_json,
                user_answer, is_correct, mistake_type, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                topic_id,
                concept_id,
                question["question"],
                json.dumps(question, ensure_ascii=False),
                user_answer,
                int(is_correct),
                mistake_type,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        return int(cursor.lastrowid)


def get_ai_tutor_attempts(session_id: int) -> list[sqlite3.Row]:
    with connection() as conn:
        return conn.execute(
            """
            SELECT * FROM ai_tutor_attempts
            WHERE session_id = ?
            ORDER BY id
            """,
            (session_id,),
        ).fetchall()


def finalize_ai_tutor_attempts(
    session_id: int,
    concept_id: str,
    correct_count: int,
    rating: str,
    summary: str,
) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE ai_tutor_attempts
            SET rating = ?, summary = ?
            WHERE session_id = ?
            """,
            (rating, summary, session_id),
        )
        conn.execute(
            """
            UPDATE tutor_sessions
            SET rating = ?, correct_count = ?
            WHERE id = ?
            """,
            (rating, correct_count, session_id),
        )


def finish_tutor_session(
    session_id: int,
    summary: dict[str, str],
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO learning_summaries(
                session_id, content, mastered, mistakes, insight,
                next_suggestion, review_focus, rating, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                summary["content"],
                summary["mastered"],
                summary["mistakes"],
                summary["insight"],
                summary["next_suggestion"],
                summary["review_focus"],
                summary.get("rating", ""),
                now,
            ),
        )
        summary_id = int(cursor.lastrowid)
        conn.execute(
            """
            UPDATE tutor_sessions
            SET status = 'completed', ended_at = ?, summary_id = ?
            WHERE id = ?
            """,
            (now, summary_id, session_id),
        )
    return summary_id


def save_question_dialogue_summary(
    summary: dict[str, str],
    question_images: list[str] | None = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with connection() as conn:
        _add_column(
            conn,
            "learning_summaries",
            "question_images_json",
            "TEXT NOT NULL DEFAULT '[]'",
        )
        cursor = conn.execute(
            """
            INSERT INTO learning_summaries(
                content, mastered, mistakes, insight,
                next_suggestion, review_focus, rating,
                question_images_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary["content"],
                summary["mastered"],
                summary["mistakes"],
                summary["insight"],
                summary["next_suggestion"],
                summary["review_focus"],
                summary.get("rating", ""),
                json.dumps(question_images or [], ensure_ascii=False),
                now,
            ),
        )
        return int(cursor.lastrowid)


def set_summary_favorite(summary_id: int, favorited: bool) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE learning_summaries SET favorited = ? WHERE id = ?",
            (int(favorited), summary_id),
        )


def get_summaries(
    limit: int = 10, favorites_only: bool = False
) -> list[sqlite3.Row]:
    where = "WHERE favorited = 1" if favorites_only else ""
    with connection() as conn:
        return conn.execute(
            f"""
            SELECT * FROM learning_summaries
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def get_summary(summary_id: int) -> sqlite3.Row | None:
    with connection() as conn:
        return conn.execute(
            "SELECT * FROM learning_summaries WHERE id = ?",
            (summary_id,),
        ).fetchone()


def save_favorite_reflection(
    content: str, review_focus: str
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO learning_summaries(
                content, insight, review_focus, favorited, created_at
            ) VALUES (?, ?, ?, 1, ?)
            """,
            (f"**我的反思**\n{content}", content, review_focus, now),
        )
        return int(cursor.lastrowid)


def resolve_wrong_question(question_id: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE wrong_questions SET resolved = 1 WHERE question_id = ?",
            (question_id,),
        )


def delete_wrong_question(question_id: str) -> None:
    """Remove one wrong-question record without deleting the question itself."""
    with connection() as conn:
        conn.execute(
            "DELETE FROM wrong_questions WHERE question_id = ?",
            (question_id,),
        )


def get_wrong_questions(include_resolved: bool = False) -> list[sqlite3.Row]:
    where = "" if include_resolved else "WHERE resolved = 0"
    with connection() as conn:
        return conn.execute(
            f"""
            SELECT * FROM wrong_questions
            {where}
            ORDER BY resolved, last_wrong_at DESC
            """
        ).fetchall()


def save_topic_progress(
    topic_id: str,
    mastery: float,
    diagnostic_score: float | None = None,
    completed: bool = False,
    review_days: int = 1,
) -> None:
    now = datetime.now()
    review_at = now + timedelta(days=review_days)
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO topic_progress(
                topic_id, mastery, diagnostic_score, completed,
                last_studied_at, next_review_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic_id) DO UPDATE SET
                mastery = excluded.mastery,
                diagnostic_score = COALESCE(excluded.diagnostic_score, diagnostic_score),
                completed = MAX(completed, excluded.completed),
                last_studied_at = excluded.last_studied_at,
                next_review_at = excluded.next_review_at
            """,
            (
                topic_id,
                max(0.0, min(1.0, mastery)),
                diagnostic_score,
                int(completed),
                now.isoformat(timespec="seconds"),
                review_at.isoformat(timespec="seconds"),
            ),
        )


def get_topic_progress() -> dict[str, sqlite3.Row]:
    with connection() as conn:
        rows = conn.execute("SELECT * FROM topic_progress").fetchall()
    return {row["topic_id"]: row for row in rows}


def get_due_reviews() -> list[sqlite3.Row]:
    now = datetime.now().isoformat(timespec="seconds")
    with connection() as conn:
        return conn.execute(
            """
            SELECT * FROM topic_progress
            WHERE next_review_at IS NOT NULL AND next_review_at <= ?
            ORDER BY next_review_at
            """,
            (now,),
        ).fetchall()


def _calculate_streak(study_dates: set[date]) -> int:
    if not study_dates:
        return 0
    cursor = date.today()
    if cursor not in study_dates:
        cursor -= timedelta(days=1)
    streak = 0
    while cursor in study_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def get_stats() -> dict[str, float | int]:
    today = date.today().isoformat()
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    with connection() as conn:
        activity = conn.execute(
            """
            SELECT
                COALESCE(SUM(duration_seconds), 0) AS total,
                COALESCE(SUM(CASE WHEN substr(recorded_at, 1, 10) = ?
                    THEN duration_seconds ELSE 0 END), 0) AS today,
                COALESCE(SUM(CASE WHEN substr(recorded_at, 1, 10) >= ?
                    THEN duration_seconds ELSE 0 END), 0) AS week
            FROM study_activity
            """,
            (today, week_start),
        ).fetchone()
        legacy_total = conn.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) AS total FROM study_sessions"
        ).fetchone()["total"]
        attempts = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(is_correct), 0) AS correct,
                COALESCE(SUM(CASE WHEN substr(attempted_at, 1, 10) = ?
                    THEN 1 ELSE 0 END), 0) AS today_total,
                COALESCE(SUM(CASE WHEN substr(attempted_at, 1, 10) = ?
                    THEN is_correct ELSE 0 END), 0) AS today_correct
            FROM quiz_attempts
            """,
            (today, today),
        ).fetchone()
        tutor_attempts = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN assessment = 'correct' THEN 1 ELSE 0 END), 0)
                    AS correct,
                COALESCE(SUM(CASE WHEN substr(created_at, 1, 10) = ?
                    THEN 1 ELSE 0 END), 0) AS today_total,
                COALESCE(SUM(CASE WHEN substr(created_at, 1, 10) = ?
                    AND assessment = 'correct' THEN 1 ELSE 0 END), 0)
                    AS today_correct
            FROM tutor_messages
            WHERE role = 'assistant' AND assessment IS NOT NULL
            """,
            (today, today),
        ).fetchone()
        current_concepts = get_concepts()
        current_ids = {item["id"] for item in current_concepts}
        current_lessons = {item["topic_id"] for item in current_concepts}
        mastery_rows = conn.execute(
            "SELECT concept_id, topic_id, mastery FROM concept_mastery"
        ).fetchall()
        study_rows = conn.execute(
            """
            SELECT DISTINCT substr(recorded_at, 1, 10) AS study_date
            FROM study_activity
            UNION
            SELECT DISTINCT substr(attempted_at, 1, 10) AS study_date
            FROM quiz_attempts
            UNION
            SELECT DISTINCT substr(created_at, 1, 10) AS study_date
            FROM tutor_messages
            WHERE role = 'user'
            """
        ).fetchall()

    study_dates = {
        date.fromisoformat(row["study_date"])
        for row in study_rows
        if row["study_date"]
    }
    total_attempts = int(attempts["total"]) + int(tutor_attempts["total"])
    today_attempts = int(attempts["today_total"]) + int(tutor_attempts["today_total"])
    total_correct = int(attempts["correct"]) + int(tutor_attempts["correct"])
    today_correct = int(attempts["today_correct"]) + int(
        tutor_attempts["today_correct"]
    )
    lesson_mastery: dict[str, list[float]] = {
        lesson_id: [] for lesson_id in current_lessons
    }
    for row in mastery_rows:
        if row["concept_id"] in current_ids and row["topic_id"] in lesson_mastery:
            lesson_mastery[row["topic_id"]].append(float(row["mastery"]))
    completed = sum(
        bool(values) and sum(values) / len(values) >= 0.8
        for values in lesson_mastery.values()
    )
    return {
        "today_seconds": int(activity["today"]),
        "week_seconds": int(activity["week"]),
        "total_seconds": int(activity["total"]) + int(legacy_total),
        "today_attempts": today_attempts,
        "today_accuracy": (
            today_correct / today_attempts
            if today_attempts
            else 0.0
        ),
        "total_attempts": total_attempts,
        "accuracy": (
            total_correct / total_attempts if total_attempts else 0.0
        ),
        "completed_topics": int(completed),
        "streak": _calculate_streak(study_dates),
    }


def get_daily_stats(days: int = 14) -> list[sqlite3.Row]:
    start = (date.today() - timedelta(days=days - 1)).isoformat()
    with connection() as conn:
        return conn.execute(
            """
            WITH dates AS (
                SELECT substr(recorded_at, 1, 10) AS study_date
                FROM study_activity
                WHERE substr(recorded_at, 1, 10) >= ?
                UNION
                SELECT substr(attempted_at, 1, 10)
                FROM quiz_attempts
                WHERE substr(attempted_at, 1, 10) >= ?
                UNION
                SELECT substr(created_at, 1, 10)
                FROM tutor_messages
                WHERE role = 'user' AND substr(created_at, 1, 10) >= ?
            ),
            durations AS (
                SELECT substr(recorded_at, 1, 10) AS study_date,
                       SUM(duration_seconds) AS seconds
                FROM study_activity
                GROUP BY substr(recorded_at, 1, 10)
            ),
            raw_attempts AS (
                SELECT substr(attempted_at, 1, 10) AS study_date,
                       1 AS attempts, is_correct AS correct
                FROM quiz_attempts
                UNION ALL
                SELECT substr(created_at, 1, 10) AS study_date,
                       1 AS attempts,
                       CASE WHEN assessment = 'correct' THEN 1 ELSE 0 END AS correct
                FROM tutor_messages
                WHERE role = 'assistant' AND assessment IS NOT NULL
            ),
            attempts AS (
                SELECT study_date, SUM(attempts) AS attempts, SUM(correct) AS correct
                FROM raw_attempts
                GROUP BY study_date
            )
            SELECT dates.study_date,
                   COALESCE(durations.seconds, 0) AS seconds,
                   COALESCE(attempts.attempts, 0) AS attempts,
                   COALESCE(attempts.correct, 0) AS correct
            FROM dates
            LEFT JOIN durations USING(study_date)
            LEFT JOIN attempts USING(study_date)
            ORDER BY dates.study_date DESC
            """,
            (start, start, start),
        ).fetchall()


def _bank_question(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["question_images"] = json.loads(value.pop("question_images_json"))
    value["answer_images"] = json.loads(value.pop("answer_images_json"))
    value["auto_gradable"] = bool(value["auto_gradable"])
    return value


def get_question_bank_sections() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT s.*,
                   COUNT(a.id) AS attempts,
                   COALESCE(SUM(a.is_correct), 0) AS correct_attempts,
                   COUNT(DISTINCT a.question_id) AS answered_questions
            FROM question_bank_sections s
            LEFT JOIN quiz_attempts a ON a.topic_id = s.id
            GROUP BY s.id
            ORDER BY s.source,
                     s.batch,
                     CASE s.subject
                         WHEN 'calculus' THEN 1
                         WHEN 'linear_algebra' THEN 2
                         WHEN 'probability' THEN 3
                         ELSE 4
                     END,
                     s.chapter_number,
                     CASE s.phase
                         WHEN 'foundation' THEN 1
                         WHEN 'comprehensive' THEN 2
                         WHEN 'extension' THEN 3
                         ELSE 4
                     END
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_question_bank_overview() -> dict[str, int]:
    sections = get_question_bank_sections()
    explored = sum(int(section["attempts"]) >= 5 for section in sections)
    return {
        "sections": len(sections),
        "explored": explored,
        "questions": sum(int(section["question_count"]) for section in sections),
    }


def get_question_bank_question(question_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT q.*, s.title AS section_title, s.phase, s.subject,
                   s.source, s.source_label
            FROM question_bank q
            JOIN question_bank_sections s ON s.id = q.section_id
            WHERE q.id = ?
            """,
            (question_id,),
        ).fetchone()
    return _bank_question(row) if row else None


def get_question_knowledge(question_id: str) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT n.id, n.subject, n.chapter_number, n.phase, n.title,
                   n.source, n.confidence, qk.relation, qk.confidence AS tag_confidence
                   , qk.source AS tag_source
            FROM question_knowledge qk
            JOIN knowledge_nodes n ON n.id = qk.knowledge_id
            WHERE qk.question_id = ?
            ORDER BY CASE qk.relation
                         WHEN 'direct' THEN 1
                         WHEN 'prerequisite' THEN 2
                         WHEN 'primary' THEN 3
                         ELSE 4
                     END,
                     qk.confidence DESC
            """,
            (question_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def save_question_knowledge(
    question_id: str,
    tags: list[dict[str, Any]],
) -> None:
    """Replace classifier-owned tags while retaining the chapter fallback."""
    allowed_relations = {"direct", "prerequisite"}
    with connection() as conn:
        valid_nodes = {
            str(row["id"])
            for row in conn.execute("SELECT id FROM knowledge_nodes")
        }
        conn.execute(
            """
            DELETE FROM question_knowledge
            WHERE question_id = ? AND source != 'section_fallback'
            """,
            (question_id,),
        )
        for tag in tags:
            knowledge_id = str(tag.get("knowledge_id", ""))
            relation = str(tag.get("relation", "direct"))
            if knowledge_id not in valid_nodes or relation not in allowed_relations:
                continue
            confidence = min(1.0, max(0.0, float(tag.get("confidence", 0.0))))
            conn.execute(
                """
                INSERT OR REPLACE INTO question_knowledge(
                    question_id, knowledge_id, relation, confidence, source
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    question_id,
                    knowledge_id,
                    relation,
                    confidence,
                    str(tag.get("source", "ai_classifier")),
                ),
            )


def get_section_mastery(section_id: str) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT s.id, s.subject, s.chapter_number, s.phase, s.title,
                   s.question_count,
                   COUNT(a.id) AS attempts,
                   COALESCE(SUM(a.is_correct), 0) AS correct_attempts,
                   COUNT(DISTINCT a.question_id) AS answered_questions
            FROM question_bank_sections s
            LEFT JOIN quiz_attempts a ON a.topic_id = s.id
            WHERE s.id = ?
            GROUP BY s.id
            """,
            (section_id,),
        ).fetchone()
    if not row:
        return {}
    value = dict(row)
    attempts = int(value["attempts"])
    value["accuracy"] = (
        int(value["correct_attempts"]) / attempts if attempts else 0.0
    )
    value["coverage"] = (
        int(value["answered_questions"]) / int(value["question_count"])
        if int(value["question_count"])
        else 0.0
    )
    return value


def choose_daily_question(exclude_ids: list[str] | None = None) -> dict[str, Any] | None:
    """Choose one question from all subjects using learning evidence.

    Unresolved wrong questions win. Otherwise, select a low-accuracy section
    and prefer unseen questions. The returned question is always from the
    fixed bank; no model is involved in question generation.
    """
    excluded = set(exclude_ids or [])
    with connection() as conn:
        wrong_rows = conn.execute(
            """
            SELECT q.id
            FROM wrong_questions w
            JOIN question_bank q ON q.id = w.question_id
            JOIN question_bank_sections s ON s.id = q.section_id
            WHERE w.resolved = 0
            ORDER BY w.wrong_count DESC, w.last_wrong_at ASC
            """
        ).fetchall()
        wrong_ids = [str(row["id"]) for row in wrong_rows if row["id"] not in excluded]
        if wrong_ids:
            chosen = random.choice(wrong_ids)
            return get_question_bank_question(chosen)

        section_rows = conn.execute(
            """
            SELECT s.id,
                   COUNT(a.id) AS attempts,
                   COALESCE(SUM(a.is_correct), 0) AS correct_attempts
            FROM question_bank_sections s
            LEFT JOIN quiz_attempts a ON a.topic_id = s.id
            GROUP BY s.id
            ORDER BY
                CASE WHEN COUNT(a.id) = 0 THEN 0 ELSE 1 END,
                CASE WHEN COUNT(a.id) = 0 THEN 0
                     ELSE COALESCE(SUM(a.is_correct), 0) * 1.0 / COUNT(a.id)
                END,
                RANDOM()
            """
        ).fetchall()
        excluded_clause = (
            f"AND q.id NOT IN ({', '.join('?' for _ in excluded)})"
            if excluded
            else ""
        )
        for section in section_rows:
            rows = conn.execute(
                f"""
                SELECT q.*, s.title AS section_title, s.phase, s.subject,
                       s.source, s.source_label,
                       CASE WHEN EXISTS(
                           SELECT 1 FROM quiz_attempts a
                           WHERE a.question_id = q.id
                       ) THEN 1 ELSE 0 END AS seen
                FROM question_bank q
                JOIN question_bank_sections s ON s.id = q.section_id
                WHERE q.section_id = ?
                  {excluded_clause}
                ORDER BY seen, RANDOM()
                LIMIT 1
                """,
                (section["id"], *excluded),
            ).fetchall()
            if rows:
                return _bank_question(rows[0])
    return None


def choose_repair_questions(
    section_id: str,
    exclude_ids: list[str] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return fixed-bank candidates for a bounded repair step.

    Comprehensive questions prefer a foundation section from the same
    subject/chapter. Otherwise the current section is used.
    """
    excluded = set(exclude_ids or [])
    with connection() as conn:
        section = conn.execute(
            "SELECT subject, chapter_number, phase FROM question_bank_sections WHERE id = ?",
            (section_id,),
        ).fetchone()
        if not section:
            return []
        target_phases = (
            ("foundation", "comprehensive")
            if section["phase"] == "comprehensive"
            else (section["phase"], "foundation", "comprehensive")
        )
        phase_placeholders = ", ".join("?" for _ in target_phases)
        excluded_clause = (
            f"AND q.id NOT IN ({', '.join('?' for _ in excluded)})"
            if excluded
            else ""
        )
        rows = conn.execute(
            f"""
            SELECT q.*, s.title AS section_title, s.phase, s.subject,
                   s.source, s.source_label,
                   CASE WHEN EXISTS(
                       SELECT 1 FROM quiz_attempts a WHERE a.question_id = q.id
                   ) THEN 1 ELSE 0 END AS seen
            FROM question_bank q
            JOIN question_bank_sections s ON s.id = q.section_id
            WHERE s.subject = ?
              AND s.chapter_number = ?
              AND s.phase IN ({phase_placeholders})
              {excluded_clause}
            ORDER BY CASE s.phase WHEN 'foundation' THEN 1 ELSE 2 END,
                     seen, RANDOM()
            LIMIT ?
            """,
            (
                section["subject"],
                section["chapter_number"],
                *target_phases,
                *excluded,
                limit,
            ),
        ).fetchall()
    return [_bank_question(row) for row in rows]


def start_daily_session(question_id: str, context: dict[str, Any]) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO daily_sessions(
                original_question_id, status, context_json, started_at
            ) VALUES (?, 'active', ?, ?)
            """,
            (question_id, json.dumps(context, ensure_ascii=False), now),
        )
    return int(cursor.lastrowid)


def update_daily_session(
    session_id: int,
    *,
    status: str,
    context: dict[str, Any],
    report: dict[str, Any] | None = None,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with connection() as conn:
        conn.execute(
            """
            UPDATE daily_sessions
            SET status = ?, context_json = ?, report_json = ?,
                finished_at = CASE WHEN ? IN ('complete', 'abandoned')
                                   THEN ? ELSE finished_at END
            WHERE id = ?
            """,
            (
                status,
                json.dumps(context, ensure_ascii=False),
                json.dumps(report, ensure_ascii=False) if report else None,
                status,
                now,
                session_id,
            ),
        )


def start_react_run(
    daily_session_id: int,
    original_question_id: str,
    context: dict[str, Any],
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO react_runs(
                daily_session_id, original_question_id, context_json, started_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                daily_session_id,
                original_question_id,
                json.dumps(context, ensure_ascii=False),
                now,
            ),
        )
    return int(cursor.lastrowid)


def record_react_step(
    run_id: int,
    step_number: int,
    action: str,
    observation: dict[str, Any],
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: dict[str, Any],
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO react_steps(
                run_id, step_number, action, observation_json,
                tool_name, tool_input_json, tool_output_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                step_number,
                action,
                json.dumps(observation, ensure_ascii=False),
                tool_name,
                json.dumps(tool_input, ensure_ascii=False),
                json.dumps(tool_output, ensure_ascii=False),
                now,
            ),
        )
        conn.execute(
            "UPDATE react_runs SET step_count = ? WHERE id = ?",
            (step_number, run_id),
        )


def finish_react_run(
    run_id: int,
    status: str,
    report: dict[str, Any] | None = None,
) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE react_runs
            SET status = ?, report_json = ?, finished_at = ?
            WHERE id = ?
            """,
            (
                status,
                json.dumps(report, ensure_ascii=False) if report else None,
                datetime.now().isoformat(timespec="seconds"),
                run_id,
            ),
        )


def choose_question_bank_questions(
    section_id: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT q.*, s.title AS section_title, s.phase, s.subject,
                   s.source, s.source_label,
                   CASE WHEN EXISTS(
                       SELECT 1 FROM quiz_attempts a
                       WHERE a.question_id = q.id
                   ) THEN 1 ELSE 0 END AS seen
            FROM question_bank q
            JOIN question_bank_sections s ON s.id = q.section_id
            WHERE q.section_id = ?
            ORDER BY seen, RANDOM()
            LIMIT ?
            """,
            (section_id, limit),
        ).fetchall()
    return [_bank_question(row) for row in rows]


def record_question_bank_attempt(
    question: dict[str, Any],
    user_answer: str,
    is_correct: bool,
    attempt_type: str = "question_bank",
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    snapshot = {
        "id": question["id"],
        "source": "fixed_question_bank",
        "section_id": question["section_id"],
        "section_title": question["section_title"],
        "knowledge_point": question["section_title"],
        "question": question["question_text"],
        "question_type": question["question_type"],
        "question_images": question["question_images"],
        "answer_text": question["answer_text"],
        "answer_choice": question["answer_choice"],
        "answer_images": question["answer_images"],
        "last_user_answer": user_answer,
    }
    question_json = json.dumps(snapshot, ensure_ascii=False)
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO quiz_attempts(
                question_id, day, knowledge_point, selected_answer,
                is_correct, attempted_at, topic_id, attempt_type, question_json
            ) VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question["id"],
                question["section_title"],
                user_answer,
                int(is_correct),
                now,
                question["section_id"],
                attempt_type,
                question_json,
            ),
        )
        if not is_correct:
            conn.execute(
                """
                INSERT INTO wrong_questions(
                    question_id, day, question_text, knowledge_point,
                    wrong_count, last_wrong_at, topic_id, question_json,
                    last_selected_answer, resolved
                ) VALUES (?, 0, ?, ?, 1, ?, ?, ?, ?, 0)
                ON CONFLICT(question_id) DO UPDATE SET
                    wrong_count = wrong_count + 1,
                    last_wrong_at = excluded.last_wrong_at,
                    topic_id = excluded.topic_id,
                    question_json = excluded.question_json,
                    last_selected_answer = excluded.last_selected_answer,
                    resolved = 0
                """,
                (
                    question["id"],
                    question["question_text"] or question["section_title"],
                    question["section_title"],
                    now,
                    question["section_id"],
                    question_json,
                    user_answer,
                ),
            )
