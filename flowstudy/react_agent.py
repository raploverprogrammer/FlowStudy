"""Bounded ReAct repair flow for the Daily Question feature.

The agent never creates questions. It observes learner data, chooses one of a
small set of actions, and asks the database for a real candidate question.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable

from flowstudy.database import (
    choose_repair_questions,
    choose_repair_questions_for_knowledge,
    choose_daily_question,
    choose_question_for_knowledge,
    finish_react_run,
    get_question_knowledge,
    get_knowledge_mastery,
    get_agent_memories,
    get_section_mastery,
    get_weak_concepts,
    record_react_step,
    save_agent_memory,
    start_react_run,
)
from services.ai_service import AIServiceError, AITutor


MAX_SUPPORT_QUESTIONS = 3
MAX_AGENT_STEPS = 12
MIN_PREREQUISITE_ATTEMPTS = 2
WEAK_PREREQUISITE_ACCURACY = 0.60
ProgressCallback = Callable[[str], None]


def _search_prerequisite_questions(
    *,
    target_knowledge_id: str,
    asked_ids: list[str],
    limit: int = 5,
    **_: Any,
) -> list[dict[str, Any]]:
    """Tool adapter for fixed-bank prerequisite retrieval."""
    if not target_knowledge_id:
        return []
    candidates = choose_repair_questions_for_knowledge(
        target_knowledge_id,
        asked_ids,
        limit=limit,
    )
    for candidate in candidates:
        candidate["repair_scope"] = "prerequisite"
    return candidates


def _search_same_section_questions(
    *,
    section_id: str,
    asked_ids: list[str],
    limit: int = 5,
    **_: Any,
) -> list[dict[str, Any]]:
    """Tool adapter for fixed-bank same-section retrieval."""
    return choose_repair_questions(section_id, asked_ids, limit=limit)


# The registry is the single boundary between Agent decisions and application
# capabilities. The model only chooses a registered name; it never receives a
# database connection or arbitrary Python callable.
AGENT_TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "inspect_question": {
        "handler": get_question_knowledge,
        "description": "读取题目的直接考点、前置知识和章节标签",
        "parameters": {
            "required": ["question_id"],
            "types": {"question_id": "str"},
        },
    },
    "get_knowledge_mastery": {
        "handler": get_knowledge_mastery,
        "description": "查询一个知识点的答题次数和正确率",
        "parameters": {
            "required": ["knowledge_id"],
            "types": {"knowledge_id": "str"},
        },
    },
    "get_section_mastery": {
        "handler": get_section_mastery,
        "description": "查询题目所属章节的整体掌握情况",
        "parameters": {
            "required": ["section_id"],
            "types": {"section_id": "str"},
        },
    },
    "get_learning_memories": {
        "handler": get_agent_memories,
        "description": "读取用户已经允许噜噜记住的学习偏好和薄弱点",
        "parameters": {"required": [], "types": {"limit": "int"}},
    },
    "get_weak_concepts": {
        "handler": get_weak_concepts,
        "description": "按答题记录、错题和近期表现找出薄弱知识方向",
        "parameters": {"required": [], "types": {"limit": "int"}},
    },
    "choose_daily_question": {
        "handler": choose_daily_question,
        "description": "从固定题库抽取一题，不生成新题",
        "parameters": {"required": [], "types": {"exclude_ids": "list"}},
    },
    "choose_question_for_knowledge": {
        "handler": choose_question_for_knowledge,
        "description": "从固定题库检索指定知识点的题目，不生成新题",
        "parameters": {
            "required": ["knowledge_id"],
            "types": {"knowledge_id": "str", "exclude_ids": "list"},
        },
    },
    "search_prerequisite_questions": {
        "handler": _search_prerequisite_questions,
        "description": "从固定题库检索某个前置知识的未做题",
        "parameters": {
            "required": ["target_knowledge_id", "asked_ids"],
            "types": {
                "target_knowledge_id": "str",
                "asked_ids": "list",
                "limit": "int",
            },
        },
    },
    "search_same_section_questions": {
        "handler": _search_same_section_questions,
        "description": "从固定题库检索当前章节的未做题",
        "parameters": {
            "required": ["section_id", "asked_ids"],
            "types": {"section_id": "str", "asked_ids": "list", "limit": "int"},
        },
    },
}

ACTION_TOOL_MAP = {
    "practice_prerequisite": "search_prerequisite_questions",
    "practice_same_section": "search_same_section_questions",
}


def agent_tool_catalog() -> list[dict[str, Any]]:
    """Return the safe tool contract that can be shown to an LLM planner."""
    json_types = {"str": "string", "int": "integer", "list": "array"}
    catalog: list[dict[str, Any]] = []
    for name, definition in AGENT_TOOL_REGISTRY.items():
        parameters = definition.get("parameters", {})
        types = parameters.get("types", {})
        catalog.append(
            {
                "name": name,
                "description": definition.get("description", ""),
                "parameters": {
                    "type": "object",
                    "properties": {
                        parameter: {"type": json_types.get(expected, "string")}
                        for parameter, expected in types.items()
                    },
                    "required": list(parameters.get("required", [])),
                    "additionalProperties": False,
                },
            }
        )
    return catalog


def call_agent_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    """Execute one allowlisted Agent tool with a small boundary validator."""
    tool = AGENT_TOOL_REGISTRY.get(tool_name)
    if tool is None:
        raise ValueError(f"未知 Agent 工具：{tool_name}")
    parameters = tool.get("parameters", {})
    missing = [
        name
        for name in parameters.get("required", [])
        if name not in arguments or arguments[name] in (None, "")
    ]
    if missing:
        raise ValueError(f"工具 {tool_name} 缺少参数：{', '.join(missing)}")
    for name, expected in parameters.get("types", {}).items():
        if name not in arguments:
            continue
        value = arguments[name]
        valid = (
            isinstance(value, str)
            if expected == "str"
            else isinstance(value, list)
            if expected == "list"
            else isinstance(value, int) and not isinstance(value, bool)
            if expected == "int"
            else True
        )
        if not valid:
            raise ValueError(f"工具 {tool_name} 的参数 {name} 类型不正确")
    if "limit" in arguments:
        arguments = {**arguments, "limit": max(1, min(int(arguments["limit"]), 10))}
    return tool["handler"](**arguments)


def _emit(
    state: dict[str, Any],
    progress: ProgressCallback | None,
    kind: str,
    message: str,
) -> None:
    """Record a ReAct event and show its safe summary without internal labels."""
    state.setdefault("trace", []).append({"kind": kind, "message": message})
    if progress:
        if kind in {"观察", "行动"}:
            progress(message)
        else:
            progress(f"**{kind}**：{message}")


def _knowledge_summary(knowledge: list[dict[str, Any]]) -> str:
    """Format knowledge tags by relation instead of mixing them together.

    The chapter fallback is useful for candidate selection, but it should not
    be presented as a fine-grained skill. Keeping it on its own line also makes
    incomplete tagging visible to the learner.
    """
    direct = []
    prerequisites = []
    fallback = []
    for item in knowledge:
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        relation = str(item.get("relation", "")).strip()
        source = str(item.get("tag_source", item.get("source", ""))).strip()
        if source == "section_fallback" or relation == "primary":
            fallback.append(title)
        elif relation == "prerequisite":
            prerequisites.append(title)
        elif relation == "direct":
            direct.append(title)

    def unique_titles(titles: list[str]) -> list[str]:
        return list(dict.fromkeys(titles))

    direct = unique_titles(direct)
    prerequisites = unique_titles(prerequisites)
    fallback = unique_titles(fallback)
    lines = ["知识标签："]
    lines.append(
        "  - 直接考点：" + ("、".join(direct) if direct else "暂未精确识别")
    )
    lines.append(
        "  - 前置知识："
        + ("、".join(prerequisites) if prerequisites else "暂无已标注前置知识")
    )
    if fallback:
        lines.append("  - 章节范围：" + "、".join(fallback))
    return "\n".join(lines)


def _weak_prerequisites(
    knowledge: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        item
        for item in _prerequisite_mastery(knowledge)
        if (
            item["mastery"]["attempts"] >= MIN_PREREQUISITE_ATTEMPTS
            and item["mastery"]["accuracy"] < WEAK_PREREQUISITE_ACCURACY
        )
    ]


def _prerequisite_mastery(
    knowledge: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mastery_rows: list[dict[str, Any]] = []
    for item in knowledge:
        if str(item.get("relation", "")) != "prerequisite":
            continue
        mastery = call_agent_tool(
            "get_knowledge_mastery", {"knowledge_id": str(item["id"])}
        )
        mastery_rows.append({**item, "mastery": mastery})
    return mastery_rows


def _weak_prerequisite_summary(weak: list[dict[str, Any]]) -> str:
    if not weak:
        return "没有发现达到阈值的薄弱前置知识"
    labels = []
    for item in weak:
        mastery = item["mastery"]
        labels.append(
            f"{item['title']}（已答{mastery['attempts']}次，正确率{mastery['accuracy']:.0%}）"
        )
    return "、".join(labels)


def _prerequisite_mastery_summary(
    mastery_rows: list[dict[str, Any]],
) -> str:
    if not mastery_rows:
        return "这道题暂未标注可用的前置知识"
    labels = []
    for item in mastery_rows:
        mastery = item["mastery"]
        attempts = int(mastery["attempts"])
        accuracy = f"{mastery['accuracy']:.0%}" if attempts else "暂无记录"
        labels.append(f"{item['title']}（已答{attempts}次，正确率{accuracy}）")
    return "、".join(labels)


def _wants_practice_question(message: str) -> bool:
    """Recognize only clear practice requests for the offline fallback.

    The normal path lets DeepSeek classify intent semantically. This local
    check is deliberately conservative so phrases such as "题目这里为何"
    remain ordinary explanation requests during an API outage.
    """
    text = re.sub(r"\s+", "", message)
    patterns = (
        r"(?:给我|请给我|帮我|能否|可以|想要|想再|再给我|安排|抽|找|换).{0,5}(?:一道|一题|个题|题目|练习题)",
        r"(?:出|来|做|练|再来).{0,4}(?:一道|一题|个题|题|练习)",
        r"(?:考考|测测|测试|检测|检验).{0,8}(?:我|一下|掌握|知识|水平|自己)",
        r"(?:能生成题目检测我|能出题检测我|有没有类似题)",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _fallback_diagnosis_opening(
    *,
    knowledge: list[dict[str, Any]],
    prerequisite_mastery: list[dict[str, Any]],
    weak_prerequisites: list[dict[str, Any]],
) -> str:
    """Explain the first diagnostic focus when the planner is unavailable."""
    direct = next(
        (
            str(item["title"])
            for item in knowledge
            if str(item.get("relation", "")) == "direct"
        ),
        "当前章节的核心考点",
    )
    target = weak_prerequisites[0] if weak_prerequisites else None
    if target is None:
        target = next(
            (
                item
                for item in prerequisite_mastery
                if int(item["mastery"].get("attempts", 0)) > 0
            ),
            None,
        )
    if target:
        mastery = target["mastery"]
        attempts = int(mastery.get("attempts", 0))
        accuracy = float(mastery.get("accuracy", 0.0))
        return (
            f"这道题主要考查「{direct}」。我先看了你的前置记录，"
            f"「{target['title']}」已答 {attempts} 次、正确率 {accuracy:.0%}，"
            "它是目前更值得先确认的环节。你先说说自己在这道题里是从哪一步开始不确定的？"
        )
    prerequisite = next(
        (str(item["title"]) for item in prerequisite_mastery),
        "相关基础知识",
    )
    return (
        f"这道题主要考查「{direct}」，我也检查了它依赖的「{prerequisite}」。"
        "目前记录还不足以直接判断你的具体漏洞，你先说说刚才是依据哪一步选出这个答案的？"
    )


def _local_diagnosis_action(
    *,
    state: dict[str, Any],
    user_message: str,
    weak_prerequisites: list[dict[str, Any]],
) -> dict[str, Any]:
    """Keep the ReAct loop moving when the planner endpoint is temporarily busy."""
    support_results = state.get("support_results", [])
    last_result = support_results[-1]["is_correct"] if support_results else None
    wants_practice = _wants_practice_question(user_message)
    if wants_practice and weak_prerequisites and len(support_results) < MAX_SUPPORT_QUESTIONS:
        target = weak_prerequisites[0]
        return {
            "reply": (
                f"可以。根据当前掌握度，我先从固定题库抽一道「{target['title']}」的题，"
                "做完再决定是否继续。"
            ),
            "next_action": "practice_prerequisite",
            "target_knowledge_id": target["id"],
            "gap": f"用户要求练习，且前置知识掌握度偏低：{target['title']}",
        }
    if wants_practice and len(support_results) < MAX_SUPPORT_QUESTIONS:
        return {
            "reply": "可以。我从固定题库抽一道当前章节的题来检测一下，不临时编题。",
            "next_action": "practice_same_section",
            "target_knowledge_id": None,
            "gap": "用户明确要求练习当前章节",
        }
    if last_result is True:
        return {
            "reply": "这道补充题已经答对了。我们回到原题，验证这个方法能不能迁移过去。",
            "next_action": "verify_original",
            "target_knowledge_id": None,
            "gap": "补充题已答对，需要验证迁移能力",
        }
    if weak_prerequisites and len(support_results) < 3:
        target = weak_prerequisites[0]
        return {
            "reply": (
                f"我根据你的答题记录先定位到「{target['title']}」掌握得不够稳，"
                "先补一道对应题，再回到原题。"
            ),
            "next_action": "practice_prerequisite",
            "target_knowledge_id": target["id"],
            "gap": f"前置知识掌握度偏低：{target['title']}",
        }
    return {
        "reply": "我先不直接给结论。请具体说说你在题目的哪一步卡住了，或写出你已经尝试的思路。",
        "next_action": "ask_clarification",
        "target_knowledge_id": None,
        "gap": "需要继续确认具体卡点",
    }


def start_diagnosis(
    *,
    daily_session_id: int,
    original_question: dict[str, Any],
    original_user_answer: str,
) -> dict[str, Any]:
    """Start an interactive diagnosis without automatically showing a support question."""
    knowledge = call_agent_tool(
        "inspect_question", {"question_id": original_question["id"]}
    )
    weak = _weak_prerequisites(knowledge)
    prerequisite_mastery = _prerequisite_mastery(knowledge)
    mastery = call_agent_tool(
        "get_section_mastery", {"section_id": original_question["section_id"]}
    )
    tutor = AITutor()
    opening_source = "本地诊断策略"
    if tutor.enabled:
        try:
            opening = tutor.diagnose_question_opening(
                question=original_question,
                original_user_answer=original_user_answer,
                knowledge_tags=knowledge,
                prerequisite_mastery=prerequisite_mastery,
                weak_prerequisites=weak,
            )
            opening_source = "DeepSeek Agent"
        except AIServiceError:
            opening = _fallback_diagnosis_opening(
                knowledge=knowledge,
                prerequisite_mastery=prerequisite_mastery,
                weak_prerequisites=weak,
            )
            opening_source = "本地诊断策略（DeepSeek 暂时不可用）"
    else:
        opening = _fallback_diagnosis_opening(
            knowledge=knowledge,
            prerequisite_mastery=prerequisite_mastery,
            weak_prerequisites=weak,
        )
    state: dict[str, Any] = {
        "status": "diagnosis",
        "original_question": original_question,
        "original_question_id": original_question["id"],
        "original_user_answer": original_user_answer,
        "knowledge_tags": knowledge,
        "section_mastery": mastery,
        "weak_prerequisites": weak,
        "prerequisite_mastery": prerequisite_mastery,
        "dialogue": [
            {
                "role": "assistant",
                "content": opening,
            }
        ],
        "support_results": [],
        "asked_ids": [original_question["id"]],
        "current_question": None,
        "trace": [],
        "gap": "",
        "last_decision_source": opening_source,
        "decision_sources": [opening_source],
        "agent_steps": 0,
        "memory_context": get_agent_memories(12),
    }
    state["run_id"] = start_react_run(
        daily_session_id,
        original_question["id"],
        {"status": state["status"], "asked_ids": state["asked_ids"]},
    )
    _emit(
        state,
        None,
        "观察",
        f"原题属于「{original_question['section_title']}」，开始诊断这次错误。",
    )
    _emit(
        state,
        None,
        "观察",
        _knowledge_summary(knowledge),
    )
    _emit(
        state,
        None,
        "观察",
        "前置知识掌握度：\n  - "
        + _prerequisite_mastery_summary(prerequisite_mastery)
        + "。",
    )
    for item in weak:
        mastery = item["mastery"]
        save_agent_memory(
            "weak_knowledge",
            str(item["id"]),
            f"「{item['title']}」近期掌握度偏低，答题 {int(mastery.get('attempts', 0))} 次，正确率 {float(mastery.get('accuracy', 0.0)):.0%}。",
            metadata={"knowledge_id": item["id"], "accuracy": mastery.get("accuracy", 0.0)},
            source="daily_diagnosis",
            confidence=0.8,
        )
    record_react_step(
        int(state["run_id"]),
        1,
        "inspect_question",
        {
            "question_id": original_question["id"],
            "knowledge_tags": knowledge,
            "section_mastery": mastery,
            "weak_prerequisites": weak,
        },
        "inspect_question|get_knowledge_mastery",
        {"question_id": original_question["id"]},
        {
            "knowledge_count": len(knowledge),
            "weak_prerequisite_count": len(weak),
        },
    )
    return state


def diagnose_turn(
    *,
    state: dict[str, Any],
    user_message: str,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run one Agent turn and execute its next validated action."""
    started_at = time.perf_counter()
    state["agent_steps"] = int(state.get("agent_steps", 0)) + 1
    if state["agent_steps"] > MAX_AGENT_STEPS:
        message = "这轮诊断已经完成足够多的判断，我们先停在这里，避免反复打扰你。"
        state.setdefault("dialogue", []).extend(
            [{"role": "user", "content": user_message}, {"role": "assistant", "content": message}]
        )
        state["status"] = "diagnosis_complete"
        state["last_decision_source"] = "本地安全上限"
        state.setdefault("decision_sources", []).append("本地安全上限")
        _emit(state, progress, "结果", message)
        return state
    question = state["original_question"]
    knowledge = call_agent_tool(
        "inspect_question", {"question_id": question["id"]}
    )
    weak = _weak_prerequisites(knowledge)
    prerequisite_mastery = _prerequisite_mastery(knowledge)
    state["knowledge_tags"] = knowledge
    state["weak_prerequisites"] = weak
    state["prerequisite_mastery"] = prerequisite_mastery
    state["section_mastery"] = call_agent_tool(
        "get_section_mastery", {"section_id": question["section_id"]}
    )
    tutor = AITutor()
    if not tutor.enabled:
        raise AIServiceError("未配置 OPENROUTER_API_KEY，暂时无法启动错因诊断。")
    planner_fallback = False
    try:
        common_agent_args = {
            "question": question,
            "original_user_answer": state["original_user_answer"],
            "user_message": user_message,
            "knowledge_tags": knowledge,
            "section_mastery": state["section_mastery"],
            "weak_prerequisites": weak,
            "prerequisite_mastery": prerequisite_mastery,
            "dialogue": state.get("dialogue", []),
            "support_results": state.get("support_results", []),
            "memory_context": state.get("memory_context", get_agent_memories(12)),
        }
        # Native tool calls are the normal diagnosis path. The legacy JSON
        # planner remains available only as a compatibility fallback when a
        # provider does not support the OpenAI-compatible tools protocol.
        if os.getenv("FLOWSTUDY_NATIVE_FUNCTION_CALLING", "1") == "1":
            response = tutor.diagnose_question_turn_native(**common_agent_args)
            decision_source = "DeepSeek 原生 Function Calling"
        else:
            response = tutor.diagnose_question_turn(**common_agent_args)
            decision_source = "DeepSeek Agent"
    except AIServiceError as structured_error:
        # Keep the ReAct loop intact: use the latest tool observations and a
        # bounded local policy instead of bypassing the Agent with plain chat.
        response = _local_diagnosis_action(
            state=state,
            user_message=user_message,
            weak_prerequisites=weak,
        )
        planner_fallback = True
        decision_source = "本地 Agent 策略（DeepSeek 暂时不可用）"
    state["last_decision_source"] = decision_source
    state.setdefault("decision_sources", []).append(decision_source)
    dialogue = list(state.get("dialogue", []))
    dialogue.extend(
        [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": response["reply"]},
        ]
    )
    state["dialogue"] = dialogue[-12:]
    action = response["next_action"]
    wants_practice = _wants_practice_question(user_message)
    if (
        wants_practice
        and action not in {"practice_prerequisite", "practice_same_section"}
        and len(state.get("support_results", [])) < MAX_SUPPORT_QUESTIONS
    ):
        # A direct request for a question is an explicit intent. Keep the LLM
        # in charge of the general route, but prevent a prose-only answer from
        # silently skipping the fixed-bank question tool.
        action = "practice_prerequisite" if weak else "practice_same_section"
        response["next_action"] = action
        response["target_knowledge_id"] = weak[0]["id"] if weak else None
        response["reply"] = (
            "可以。我根据当前掌握情况从固定题库抽一道"
            + (f"「{weak[0]['title']}」前置题。" if weak else "当前章节题。")
        )
        state["dialogue"][-1]["content"] = response["reply"]
    tool_output: dict[str, Any] = {"reply": response["reply"], "action": action}
    if planner_fallback:
        tool_output["fallback"] = "local_react_policy_after_planner_error"
    tool_output["decision_source"] = decision_source
    executed_tool_name: str | None = None
    tool_duration_ms = 0.0
    step_error = ""
    if action in ACTION_TOOL_MAP:
        tool_name = str(response.get("tool_name") or ACTION_TOOL_MAP[action])
        if tool_name not in AGENT_TOOL_REGISTRY:
            tool_name = ACTION_TOOL_MAP[action]
        tool_arguments: dict[str, Any] = {
            "asked_ids": list(state.get("asked_ids", [])),
            "limit": 5,
        }
        native_arguments = response.get("tool_arguments")
        if isinstance(native_arguments, dict):
            tool_arguments.update(native_arguments)
        tool_arguments["asked_ids"] = list(state.get("asked_ids", []))
        tool_arguments["limit"] = min(int(tool_arguments.get("limit", 5)), 5)
        target_id = str(response.get("target_knowledge_id") or "")
        if action == "practice_prerequisite":
            prerequisite_ids = {
                str(item["id"])
                for item in knowledge
                if item.get("relation") == "prerequisite"
            }
            if target_id not in prerequisite_ids:
                target_id = str(weak[0]["id"]) if weak else ""
            tool_arguments["target_knowledge_id"] = target_id
        else:
            tool_arguments["section_id"] = question["section_id"]
        executed_tool_name = tool_name
        tool_started_at = time.perf_counter()
        try:
            candidates = call_agent_tool(tool_name, tool_arguments)
        except (ValueError, RuntimeError, OSError) as exc:
            candidates = []
            step_error = str(exc)
            tool_output["fallback"] = "tool_execution_error"
            tool_output["error"] = step_error
        tool_duration_ms = (time.perf_counter() - tool_started_at) * 1000
        native_summary = ""
        if (
            decision_source == "DeepSeek 原生 Function Calling"
            and response.get("tool_call_id")
        ):
            try:
                native_summary = tutor.complete_native_tool_call(
                    user_message=user_message,
                    tool_call_id=str(response["tool_call_id"]),
                    tool_name=tool_name,
                    tool_arguments=tool_arguments,
                    tool_result=[
                        {
                            "id": item.get("id"),
                            "section_title": item.get("section_title"),
                            "question_number": item.get("question_number"),
                        }
                        for item in candidates[:5]
                    ],
                )
            except AIServiceError as exc:
                tool_output["native_result_fallback"] = str(exc)
        if not candidates:
            response["reply"] = (
                "固定题库暂时没有可用的对应题目，我们先继续围绕原题梳理。"
            )
            state["dialogue"][-1]["content"] = response["reply"]
            action = "explain"
            tool_output["fallback"] = "no_prerequisite_candidate"
        else:
            candidate = candidates[0]
            scope = "prerequisite" if tool_name == "search_prerequisite_questions" else "same_section"
            candidate["repair_scope"] = scope
            state["current_question"] = candidate
            state["asked_ids"] = [
                *state.get("asked_ids", []),
                candidate["id"],
            ]
            state["status"] = "diagnosis_support"
            response["reply"] = (
                (f"{native_summary}\n\n" if native_summary else "")
                + f"好，我从固定题库抽取了一道「{candidate['section_title']}」的补充题，"
                "请在接下来的做题页面作答。"
            )
            state["dialogue"][-1]["content"] = response["reply"]
            tool_output.update(
                {
                    "tool": tool_name,
                    "knowledge_id": target_id or None,
                    "question_id": candidate["id"],
                    "question_number": candidate["question_number"],
                }
            )
            _emit(
                state,
                progress,
                "行动",
                (
                    f"根据诊断结果，从固定题库抽取「{candidate['section_title']}」中的"
                    f"{'前置知识' if scope == 'prerequisite' else '同章节'}题。"
                ),
            )
            _emit(state, progress, "结果", response["reply"])
    elif action == "verify_original":
        state["status"] = "diagnosis_retest"
        _emit(state, progress, "行动", "回到原题，验证刚才的理解是否能够迁移。")
        _emit(state, progress, "结果", response["reply"])
    elif action == "finish":
        state["status"] = "diagnosis_complete"
        _emit(state, progress, "行动", "结束错因诊断，准备生成本题对话总结。")
        _emit(state, progress, "结果", response["reply"])
    else:
        state["status"] = "diagnosis"
        _emit(state, progress, "行动", "继续根据用户回答追问或讲解。")
        _emit(state, progress, "结果", response["reply"])
    tool_output["action"] = action
    tool_output["reply"] = response["reply"]
    tool_output["tool_duration_ms"] = round(tool_duration_ms, 2)
    step = int(state["agent_steps"])
    tool_name = executed_tool_name or (
        "verify_original" if action == "verify_original" else "diagnose_question"
    )
    record_react_step(
        int(state["run_id"]),
        step,
        action,
        {
            "user_message": user_message,
            "weak_prerequisites": weak,
            "support_results": state.get("support_results", [])[-3:],
        },
        tool_name,
        {"action": action, "target_knowledge_id": response.get("target_knowledge_id")},
        tool_output,
        duration_ms=(time.perf_counter() - started_at) * 1000,
        error=step_error,
    )
    state["last_tool_duration_ms"] = round(tool_duration_ms, 2)
    state["memory_context"] = get_agent_memories(12)
    _remember_user_signal(user_message)
    return state


def _remember_user_signal(user_message: str) -> None:
    """Persist only explicit, useful preferences instead of raw chat logs."""
    text = re.sub(r"\s+", "", user_message)
    preferences = (
        ("hint_first", ("先提示", "不要直接给答案", "先别给答案"), "用户偏好先获得提示，再看完整答案。"),
        ("practice_only", ("只出题", "只想做题", "不要讲解"), "用户在当前学习中更偏好直接练习。"),
        ("explain_first", ("先讲解", "只想听讲解", "先解释"), "用户在当前学习中更偏好先听概念或思路解释。"),
    )
    for key, phrases, content in preferences:
        if any(phrase in text for phrase in phrases):
            save_agent_memory("preference", key, content, source="explicit_user_message")


def close_diagnosis(state: dict[str, Any], report: dict[str, Any]) -> None:
    """Persist the final report for the ReAct run."""
    state["status"] = "diagnosis_complete"
    finish_react_run(int(state["run_id"]), "complete", report)
