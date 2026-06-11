from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

from flowstudy.content import get_concept
from flowstudy.database import get_concept_learning_context
from services.ai_service import AIServiceError, AITutor


def _tutor() -> AITutor:
    return AITutor()


def ai_enabled() -> bool:
    return _tutor().enabled


def _rank_for_mastery(mastery: float) -> str:
    if mastery < 0.4:
        return "🌱 萌芽航海员"
    if mastery < 0.6:
        return "🌿 见习探索者"
    if mastery < 0.8:
        return "⛵ 熟练航海家"
    if mastery < 1.0:
        return "🌊 深海探索者"
    return "⭐ 传奇发现者"


def _ai_context(concept_key: str) -> dict[str, Any]:
    learning = get_concept_learning_context(concept_key)
    chapter = get_concept(concept_key)
    mastery = float(learning.get("mastery", 0.0))
    if not learning.get("recent_attempts") and not learning.get("wrong_count"):
        mastery = 0.0
    weakness = (
        f"有 {learning['wrong_count']} 次未订正错误"
        if learning.get("wrong_count")
        else (
            f"近期正确率约 {learning['recent_accuracy']:.0%}"
            if learning.get("recent_accuracy") is not None
            else "尚未形成明确学习记录"
        )
    )
    return {
        "topic": learning["topic"],
        "concept": learning["concept"],
        "breadcrumb": learning["breadcrumb"],
        "mastery": mastery,
        "rank": _rank_for_mastery(mastery),
        "weakness": weakness,
        "core_concepts": chapter.get("core_concepts", []),
        "high_frequency_points": chapter.get("high_frequency_points", []),
    }


def opening_turn(
    weak: dict[str, Any],
    recent_favorites: list[str],
) -> dict[str, Any]:
    context = _ai_context(weak["concept_id"])
    recent = [
        {"role": "user", "content": note}
        for note in recent_favorites[-5:]
        if note
    ]
    return _tutor().start_session(context, recent)


def tutor_turn(
    concept_key: str,
    current_question: dict[str, Any],
    user_answer: str,
    asked_ids: list[str],
    history: list[dict[str, str]],
) -> dict[str, Any]:
    question_number = len(asked_ids)
    result = _tutor().evaluate_answer(
        _ai_context(concept_key),
        current_question,
        user_answer,
        question_number,
        history[-10:],
    )
    reply = result["feedback"]
    if result["question"]:
        reply += (
            f"\n\n### 第 {question_number + 1} 题\n\n"
            f"{AITutor.format_question(result['question'])}"
        )
    else:
        reply += "\n\n五道题已经完成，噜噜正在整理本次航行总结。"
    return {**result, "reply": reply}


def conversation_summary(
    concept_key: str,
    messages: list[dict[str, str]],
    assessments: list[str],
    attempts: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    records = attempts or [
        {
            "is_correct": assessment == "correct",
            "mistake_type": (
                "无" if assessment == "correct" else "历史记录未细分"
            ),
        }
        for assessment in assessments
    ]
    return _tutor().generate_summary(
        _ai_context(concept_key),
        records,
        messages[-10:],
    )


def tutor_stream(
    question: str,
    options: list[str],
    knowledge_point: str,
    topic: str = "概率论",
) -> Generator[str, None, None]:
    tutor = _tutor()
    if not tutor.enabled:
        yield "请先在 .env 中配置 OPENROUTER_API_KEY。"
        return
    try:
        result = tutor._json_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是噜噜导师。只针对当前题给一个苏格拉底式短提示，"
                        "不能直接给答案。输出 JSON。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "topic": topic,
                            "knowledge_point": knowledge_point,
                            "question": question,
                            "options": options,
                            "output_schema": {"hint": "短提示"},
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            max_tokens=300,
        )
        yield str(result.get("hint", "先检查题目中的关键条件。"))
    except AIServiceError as exc:
        yield f"AI 提示暂时不可用：{exc}"
