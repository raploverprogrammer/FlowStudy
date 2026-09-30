"""Bounded ReAct repair flow for the Daily Question feature.

The agent never creates questions. It observes learner data, chooses one of a
small set of actions, and asks the database for a real candidate question.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from flowstudy.database import (
    choose_repair_questions,
    finish_react_run,
    get_question_knowledge,
    get_section_mastery,
    record_react_step,
    start_react_run,
)
from services.ai_service import AIServiceError, AITutor


MAX_SUPPORT_QUESTIONS = 3
ProgressCallback = Callable[[str], None]


def _emit(
    state: dict[str, Any],
    progress: ProgressCallback | None,
    kind: str,
    message: str,
) -> None:
    """Publish a safe, user-facing ReAct event without exposing hidden reasoning."""
    state.setdefault("trace", []).append({"kind": kind, "message": message})
    if progress:
        progress(f"**{kind}**：{message}")


def _mastery_summary(mastery: dict[str, Any]) -> str:
    if not mastery:
        return "本章节还没有可用的答题记录"
    attempts = int(mastery.get("attempts", 0))
    accuracy = float(mastery.get("accuracy", 0.0))
    coverage = float(mastery.get("coverage", 0.0))
    return (
        f"已答 {attempts} 次，正确率 {accuracy:.0%}，"
        f"题目覆盖率 {coverage:.0%}"
    )


def _knowledge_summary(knowledge: list[dict[str, Any]]) -> str:
    titles = [str(item.get("title", "")).strip() for item in knowledge]
    titles = [title for title in titles if title]
    return "、".join(titles[:3]) or "当前使用章节级知识标签"


def _candidate_summary_text(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "没有找到尚未做过的同章节候选题"
    labels = []
    for item in candidates[:3]:
        phase = "基础" if item.get("phase") == "foundation" else "综合"
        labels.append(f"{phase}题第{item.get('question_number')}题")
    suffix = "" if len(candidates) <= 3 else "等"
    return f"找到 {len(candidates)} 道候选题：" + "、".join(labels) + suffix


def _action_summary(
    action: dict[str, Any], candidates: list[dict[str, Any]]
) -> str:
    labels = {
        "practice_same_section": "继续练习当前章节",
        "practice_prerequisite": "先补当前章节的基础题",
        "verify_original": "回到原题验证迁移",
        "finish": "结束本次补课",
    }
    name = labels.get(str(action.get("action")), "调整学习路径")
    question_id = action.get("question_id")
    if question_id:
        selected = next(
            (item for item in candidates if item.get("id") == question_id),
            None,
        )
        if selected:
            phase = "基础" if selected.get("phase") == "foundation" else "综合"
            name += f"，安排{phase}题第{selected.get('question_number')}题"
    return name


def _candidate_summary(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "section_id": item["section_id"],
            "section_title": item["section_title"],
            "phase": item["phase"],
            "question_number": item["question_number"],
        }
        for item in candidates
    ]


def _fallback_action(
    original_question: dict[str, Any],
    candidates: list[dict[str, Any]],
    support_count: int,
    last_support_correct: bool | None,
) -> dict[str, Any]:
    if support_count >= MAX_SUPPORT_QUESTIONS:
        return {
            "action": "verify_original",
            "question_id": None,
            "gap": "补充题数量已达到本次上限",
            "user_message": "补充题已经够了，现在回到原题验证是否真正理解。",
        }
    if last_support_correct is True:
        return {
            "action": "verify_original",
            "question_id": None,
            "gap": "补充题已答对，需要回到原题验证迁移",
            "user_message": "这一步已经答对了，我们回到原题验证能不能迁移使用。",
        }
    if not candidates:
        return {
            "action": "verify_original",
            "question_id": None,
            "gap": "当前章节没有更多未做补充题",
            "user_message": "当前章节没有合适的未做题目，我们回到原题。",
        }
    prefer_prerequisite = (
        original_question.get("phase") == "comprehensive"
        and candidates[0].get("phase") == "foundation"
    )
    return {
        "action": "practice_prerequisite" if prefer_prerequisite else "practice_same_section",
        "question_id": candidates[0]["id"],
        "gap": "需要通过相关题巩固当前章节",
        "user_message": (
            "这道综合题暴露出基础环节还不稳，先做一道基础题。"
            if prefer_prerequisite
            else "先继续练习同一章节，但换一道题确认问题在哪里。"
        ),
    }


def _choose_action(
    *,
    original_question: dict[str, Any],
    original_user_answer: str,
    support_results: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    support_count: int,
    last_support_correct: bool | None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    knowledge = get_question_knowledge(original_question["id"])
    mastery = get_section_mastery(original_question["section_id"])
    observation = {
        "original_question_id": original_question["id"],
        "original_section": original_question["section_title"],
        "original_phase": original_question["phase"],
        "original_user_answer": original_user_answer,
        "knowledge_tags": knowledge,
        "section_mastery": mastery,
        "support_count": support_count,
        "last_support_correct": last_support_correct,
        "support_results": support_results[-3:],
    }
    tutor = AITutor()
    if tutor.enabled:
        try:
            action = tutor.decide_repair_action(
                observation=observation,
                candidates=candidates,
            )
        except AIServiceError:
            action = _fallback_action(
                original_question,
                candidates,
                support_count,
                last_support_correct,
            )
    else:
        action = _fallback_action(
            original_question,
            candidates,
            support_count,
            last_support_correct,
        )
    return action, observation, knowledge


def start_repair(
    *,
    daily_session_id: int,
    original_question: dict[str, Any],
    original_user_answer: str,
    asked_ids: list[str],
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "status": "repair",
        "original_question": original_question,
        "original_question_id": original_question["id"],
        "original_user_answer": original_user_answer,
        "support_count": 0,
        "support_results": [],
        "asked_ids": list(dict.fromkeys([*asked_ids, original_question["id"]])),
        "current_question": None,
        "gap": "",
        "message": "",
        "trace": [],
    }
    _emit(
        state,
        progress,
        "观察",
        f"原题属于「{original_question['section_title']}」，本次回答判定为错误。",
    )
    _emit(
        state,
        progress,
        "行动",
        "查询这道题的知识标签、章节掌握度和近期答题记录。",
    )
    run_id = start_react_run(
        daily_session_id,
        original_question["id"],
        {"status": state["status"], "asked_ids": state["asked_ids"]},
    )
    state["run_id"] = run_id
    candidates = choose_repair_questions(
        original_question["section_id"],
        state["asked_ids"],
        limit=5,
    )
    action, observation, _ = _choose_action(
        original_question=original_question,
        original_user_answer=original_user_answer,
        support_results=[],
        candidates=candidates,
        support_count=0,
        last_support_correct=None,
    )
    _emit(
        state,
        progress,
        "观察",
        f"知识标签：{_knowledge_summary(observation['knowledge_tags'])}；"
        f"章节掌握情况：{_mastery_summary(observation['section_mastery'])}。",
    )
    _emit(
        state,
        progress,
        "行动",
        "从固定题库筛选同章节候选题，并排除本次已经做过的题目。",
    )
    _emit(
        state,
        progress,
        "观察",
        _candidate_summary_text(candidates),
    )
    record_react_step(
        run_id,
        1,
        action["action"],
        observation,
        "get_learning_profile|get_candidate_questions",
        {"section_id": original_question["section_id"]},
        {"candidates": _candidate_summary(candidates)},
    )
    state["gap"] = action["gap"]
    state["message"] = action["user_message"]
    if action["question_id"]:
        state["current_question"] = next(
            item for item in candidates if item["id"] == action["question_id"]
        )
        _emit(state, progress, "行动", _action_summary(action, candidates))
        _emit(state, progress, "结果", action["user_message"])
    else:
        state["status"] = "original_retest"
        _emit(state, progress, "行动", _action_summary(action, candidates))
        _emit(state, progress, "结果", "当前没有合适的补充题，直接回到原题验证。")
    return state


def advance_repair(
    *,
    state: dict[str, Any],
    support_question: dict[str, Any],
    user_answer: str,
    is_correct: bool,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    _emit(
        state,
        progress,
        "观察",
        f"补充题「{support_question['section_title']}·第{support_question['question_number']}题」"
        f"回答{'正确' if is_correct else '错误'}。",
    )
    support_results = list(state.get("support_results", []))
    support_results.append(
        {
            "question_id": support_question["id"],
            "section_title": support_question["section_title"],
            "is_correct": bool(is_correct),
        }
    )
    state["support_results"] = support_results
    state["support_count"] = len(support_results)
    asked_ids = list(dict.fromkeys([*state.get("asked_ids", []), support_question["id"]]))
    state["asked_ids"] = asked_ids
    original_question = state["original_question"]
    candidates = choose_repair_questions(
        original_question["section_id"],
        asked_ids,
        limit=5,
    )
    _emit(
        state,
        progress,
        "行动",
        "结合这次答题结果，重新筛选下一步候选题。",
    )
    action, observation, _ = _choose_action(
        original_question=original_question,
        original_user_answer=state["original_user_answer"],
        support_results=support_results,
        candidates=candidates,
        support_count=state["support_count"],
        last_support_correct=bool(is_correct),
    )
    _emit(
        state,
        progress,
        "观察",
        f"当前累计完成 {state['support_count']} 道补充题；"
        f"{_candidate_summary_text(candidates)}。",
    )
    step = int(state.get("support_count", 0)) + 1
    record_react_step(
        int(state["run_id"]),
        step,
        action["action"],
        observation,
        "record_answer|get_candidate_questions",
        {
            "question_id": support_question["id"],
            "is_correct": bool(is_correct),
        },
        {"candidates": _candidate_summary(candidates)},
    )
    state["gap"] = action["gap"]
    state["message"] = action["user_message"]
    state["current_question"] = None
    if action["question_id"]:
        state["current_question"] = next(
            item for item in candidates if item["id"] == action["question_id"]
        )
        state["status"] = "repair"
        _emit(state, progress, "行动", _action_summary(action, candidates))
        _emit(state, progress, "结果", action["user_message"])
    else:
        state["status"] = "original_retest"
        _emit(state, progress, "行动", _action_summary(action, candidates))
        _emit(state, progress, "结果", "补充路径已完成，回到原题验证是否真正掌握。")
    return state


def finish_repair(
    *,
    state: dict[str, Any],
    original_retest_correct: bool,
    progress: ProgressCallback | None = None,
) -> dict[str, str]:
    _emit(
        state,
        progress,
        "观察",
        f"原题重新作答结果：{'正确' if original_retest_correct else '仍需复习'}；"
        f"本次完成 {int(state.get('support_count', 0))} 道补充题。",
    )
    facts = {
        "original_question_id": state["original_question_id"],
        "original_retest_correct": bool(original_retest_correct),
        "support_count": int(state.get("support_count", 0)),
        "support_results": state.get("support_results", []),
        "identified_gap": state.get("gap", ""),
    }
    tutor = AITutor()
    if tutor.enabled:
        try:
            _emit(state, progress, "行动", "根据本次 ReAct 轨迹生成知识补全报告。")
            report = tutor.generate_repair_report(facts)
        except AIServiceError:
            report = _fallback_report(facts)
    else:
        _emit(state, progress, "行动", "根据已记录的答题结果生成离线知识补全报告。")
        report = _fallback_report(facts)
    finish_react_run(int(state["run_id"]), "complete", {**facts, **report})
    _emit(state, progress, "结果", "报告已生成，补课记录已保存。")
    return report


def _fallback_report(facts: dict[str, Any]) -> dict[str, str]:
    support_count = int(facts["support_count"])
    repaired = bool(facts["original_retest_correct"])
    content = (
        "回到原题后已经答对，说明补充练习对当前漏洞起到了作用。"
        if repaired
        else "补充练习后仍建议复习当前章节，原题还没有完全掌握。"
    )
    return {
        "title": "本次知识补全报告",
        "content": (
            f"共完成 {support_count} 道补充题。{content}"
            f"\n\n本次记录的主要漏洞：{facts.get('identified_gap') or '当前章节基础还需巩固。'}"
        ),
        "next_suggestion": "下一次优先复习本题所属章节，再尝试同阶段的另一道题。",
    }
