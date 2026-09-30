"""Classify fixed-bank questions into curated knowledge and prerequisite nodes.

The command is resumable. It never removes the importer-owned section fallback;
when OCR or AI classification is uncertain, the question remains usable with
that fallback tag.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flowstudy.database import (  # noqa: E402
    connection,
    init_db,
    save_question_knowledge,
)
from flowstudy.knowledge_catalog import (  # noqa: E402
    catalog_nodes,
    nodes_for_section,
    prerequisite_nodes,
)
from services.ai_service import AIServiceError, AITutor  # noqa: E402


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _question_rows(
    *,
    subject: str | None,
    section_id: str | None,
    offset: int,
    limit: int,
    resume: bool,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if subject:
        clauses.append("s.subject = ?")
        params.append(subject)
    if section_id:
        clauses.append("s.id = ?")
        params.append(section_id)
    if resume:
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM question_knowledge tagged "
            "WHERE tagged.question_id = q.id AND tagged.source = 'ai_classifier')"
        )
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connection() as conn:
        rows = conn.execute(
            f"""
            SELECT q.*, s.title AS section_title, s.phase, s.subject,
                   s.chapter_number,
                   s.source, s.source_label
            FROM question_bank q
            JOIN question_bank_sections s ON s.id = q.section_id
            {where}
            ORDER BY s.subject, s.chapter_number, s.id, q.question_number
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["question_text"] = item.get("question_text", "") or ""
        result.append(item)
    return result


def _candidate_nodes(question: dict[str, Any]) -> list[dict[str, Any]]:
    direct = nodes_for_section(
        question["subject"],
        int(question["chapter_number"]),
        question["section_title"],
    )
    prerequisites = prerequisite_nodes([item["id"] for item in direct])
    merged: dict[str, dict[str, Any]] = {}
    for node in direct:
        merged[node["id"]] = {**node, "allowed_relations": ["direct"]}
    for node in prerequisites:
        if node["id"] in merged:
            merged[node["id"]]["allowed_relations"] = ["direct", "prerequisite"]
        else:
            merged[node["id"]] = {**node, "allowed_relations": ["prerequisite"]}
    return list(merged.values())


def _keyword_tags(
    question: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    text = _normalize(
        f"{question['section_title']} {question.get('question_text', '')}"
    )
    direct_candidates = [
        node for node in candidates if "direct" in node.get("allowed_relations", [])
    ]
    tags: list[dict[str, Any]] = []
    matched: list[dict[str, Any]] = []
    for node in direct_candidates:
        hits = sum(1 for hint in node.get("hints", ()) if _normalize(hint) in text)
        if hits:
            matched.append({"node": node, "hits": hits})
    for item in sorted(matched, key=lambda value: value["hits"], reverse=True)[:2]:
        tags.append(
            {
                "knowledge_id": item["node"]["id"],
                "relation": "direct",
                "confidence": min(0.82, 0.58 + item["hits"] * 0.08),
                "source": "keyword_classifier",
            }
        )
    if not tags and direct_candidates:
        # The section title is still a useful, conservative hint. The original
        # section_fallback remains in place if this weak guess is not accepted.
        tags.append(
            {
                "knowledge_id": direct_candidates[0]["id"],
                "relation": "direct",
                "confidence": 0.45,
                "source": "section_title_classifier",
            }
        )
    return tags


def _save_result(question: dict[str, Any], tags: list[dict[str, Any]]) -> str:
    save_question_knowledge(question["id"], tags)
    if any(float(tag.get("confidence", 0.0)) >= 0.6 for tag in tags):
        return "specific"
    return "low_confidence"


def classify(
    *,
    subject: str | None,
    section_id: str | None,
    offset: int,
    limit: int,
    batch_size: int,
    offline: bool,
    resume: bool,
) -> dict[str, int]:
    init_db()
    questions = _question_rows(
        subject=subject,
        section_id=section_id,
        offset=offset,
        limit=limit,
        resume=resume,
    )
    tutor = AITutor()
    stats = defaultdict(int)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for question in questions:
        grouped[question["section_id"]].append(question)

    for section_questions in grouped.values():
        for start in range(0, len(section_questions), batch_size):
            batch = section_questions[start : start + batch_size]
            candidates = _candidate_nodes(batch[0])
            results: dict[str, dict[str, Any]] = {}
            if not offline and tutor.enabled:
                try:
                    results = {
                        item["question_id"]: item
                        for item in tutor.classify_question_batch(
                            questions=batch,
                            candidate_nodes=candidates,
                        )
                    }
                    stats["ai_batches"] += 1
                except AIServiceError as exc:
                    print(f"AI batch fallback: {exc}", file=sys.stderr)
                    stats["ai_errors"] += 1
            for question in batch:
                ai_result = results.get(question["id"])
                tags = ai_result["tags"] if ai_result else _keyword_tags(question, candidates)
                level = _save_result(question, tags)
                stats[level] += 1
                if ai_result and ai_result.get("reason"):
                    stats["ai_labeled"] += 1
                if not tags or max(float(tag.get("confidence", 0.0)) for tag in tags) < 0.6:
                    stats["low_confidence"] += 1
    stats["processed"] = len(questions)
    stats["catalog_nodes"] = len(catalog_nodes())
    return dict(stats)


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify the fixed question bank")
    parser.add_argument("--subject", choices=("calculus", "linear_algebra", "probability"))
    parser.add_argument("--section-id")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="跳过已经完成 AI 标注的题目，适合中断后继续",
    )
    args = parser.parse_args()
    result = classify(
        subject=args.subject,
        section_id=args.section_id,
        offset=max(0, args.offset),
        limit=max(1, args.limit),
        batch_size=max(1, min(20, args.batch_size)),
        offline=args.offline,
        resume=args.resume,
    )
    print(" ".join(f"{key}={value}" for key, value in sorted(result.items())))


if __name__ == "__main__":
    main()
