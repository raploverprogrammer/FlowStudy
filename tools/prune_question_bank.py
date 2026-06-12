from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "flowstudy.db"
ASSET_ROOT = (ROOT / "data" / "question_bank").resolve()
KEEP_SUBJECT = "calculus"


def prune_database() -> dict[str, int]:
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        removed_sections = connection.execute(
            "SELECT COUNT(*) FROM question_bank_sections WHERE subject != ?",
            (KEEP_SUBJECT,),
        ).fetchone()[0]
        removed_questions = connection.execute(
            """
            SELECT COUNT(*)
            FROM question_bank q
            JOIN question_bank_sections s ON s.id = q.section_id
            WHERE s.subject != ?
            """,
            (KEEP_SUBJECT,),
        ).fetchone()[0]
        connection.execute("BEGIN")
        connection.execute(
            """
            DELETE FROM wrong_questions
            WHERE question_id IN (
                SELECT q.id
                FROM question_bank q
                JOIN question_bank_sections s ON s.id = q.section_id
                WHERE s.subject != ?
            )
            """,
            (KEEP_SUBJECT,),
        )
        connection.execute(
            """
            DELETE FROM quiz_attempts
            WHERE question_id IN (
                SELECT q.id
                FROM question_bank q
                JOIN question_bank_sections s ON s.id = q.section_id
                WHERE s.subject != ?
            )
            OR topic_id IN (
                SELECT id FROM question_bank_sections WHERE subject != ?
            )
            """,
            (KEEP_SUBJECT, KEEP_SUBJECT),
        )
        connection.execute(
            """
            DELETE FROM question_bank
            WHERE section_id IN (
                SELECT id FROM question_bank_sections WHERE subject != ?
            )
            """,
            (KEEP_SUBJECT,),
        )
        connection.execute(
            "DELETE FROM question_bank_sections WHERE subject != ?",
            (KEEP_SUBJECT,),
        )
        connection.commit()
        connection.execute("VACUUM")
        return {
            "sections": int(removed_sections),
            "questions": int(removed_questions),
        }
    finally:
        connection.close()


def prune_assets() -> int:
    removed = 0
    for directory in ASSET_ROOT.iterdir():
        if not directory.is_dir():
            continue
        if "-calculus-" in directory.name:
            continue
        resolved = directory.resolve()
        if resolved.parent != ASSET_ROOT:
            raise ValueError(f"Refusing to remove path outside question bank: {resolved}")
        shutil.rmtree(resolved)
        removed += 1

    manifest_path = ASSET_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = [item for item in manifest if item["subject"] == KEEP_SUBJECT]
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    analysis_headers = ASSET_ROOT / "analysis_headers.json"
    if analysis_headers.exists():
        analysis_headers.unlink()
    return removed


def main() -> None:
    database_result = prune_database()
    removed_directories = prune_assets()
    print(
        json.dumps(
            {
                "removed_sections": database_result["sections"],
                "removed_questions": database_result["questions"],
                "removed_asset_directories": removed_directories,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
