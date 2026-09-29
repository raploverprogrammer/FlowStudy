"""Build the internal question-to-knowledge index.

The first pass is deliberately conservative: every question receives a
section-level tag from importer metadata. This keeps low-quality OCR from
creating invented concepts while leaving a stable place for later reviewed
fine-grained tags.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flowstudy.database import connection, init_db


def build_index() -> dict[str, int]:
    init_db()
    with connection() as conn:
        sections = conn.execute("SELECT COUNT(*) FROM knowledge_nodes").fetchone()[0]
        tagged = conn.execute("SELECT COUNT(DISTINCT question_id) FROM question_knowledge").fetchone()[0]
        questions = conn.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0]
        fallback = conn.execute(
            "SELECT COUNT(*) FROM question_knowledge WHERE source = 'section_fallback'"
        ).fetchone()[0]
    return {
        "knowledge_nodes": int(sections),
        "questions": int(questions),
        "tagged_questions": int(tagged),
        "fallback_tags": int(fallback),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build FlowStudy question knowledge index")
    parser.parse_args()
    result = build_index()
    print(
        "knowledge_nodes={knowledge_nodes} questions={questions} "
        "tagged_questions={tagged_questions} fallback_tags={fallback_tags}".format(**result)
    )


if __name__ == "__main__":
    main()
