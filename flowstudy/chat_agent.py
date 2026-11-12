"""Open-ended Lulu conversation with natural-language action routing."""

from __future__ import annotations

import hashlib
import re
from time import perf_counter
from typing import Any, Callable

from flowstudy.database import get_agent_memories, get_weak_concepts, save_agent_memory
from flowstudy.knowledge_catalog import catalog_nodes
from flowstudy.react_agent import agent_tool_catalog, call_agent_tool
from flowstudy.agent_trace import make_trace_event, trace_to_progress
from services.ai_service import AIServiceError, AITutor


TraceCallback = Callable[[dict[str, Any]], None]


def start_chat() -> dict[str, Any]:
    memories = get_agent_memories(12)
    opening = "你可以直接告诉我想解释什么、想练哪一章，或者说说最近哪里总是出错。有什么想聊的都可以和我聊聊。"
    if memories:
        opening = "我记得你之前的一些学习情况了。你今天想先解释、练习，还是复习薄弱点？有什么想聊的也可以直接和我聊聊。"
    return {
        "messages": [{"role": "assistant", "content": opening}],
        "current_question": None,
        "memories": memories,
        "weak_concepts": [],
        "self_reported_concepts": [],
        "decision_sources": [],
        "tool_trace": [],
        "agent_trace": [],
    }


def _emit_chat_trace(
    state: dict[str, Any],
    trace_callback: TraceCallback | None,
    progress_callback: Callable[[str], None] | None,
    event_type: str,
    *,
    status: str = "started",
    tool: str = "",
    action: str = "",
    message: str = "",
    result_count: int | None = None,
    duration_ms: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record one observable execution event and publish its UI label."""
    event = make_trace_event(
        event_type,
        status=status,
        tool=tool,
        action=action,
        message=message,
        result_count=result_count,
        duration_ms=duration_ms,
        metadata=metadata,
    )
    state.setdefault("agent_trace", []).append(event)
    if trace_callback:
        trace_callback(event)
    if progress_callback:
        progress_callback(trace_to_progress(event))
    return event


def _local_action(message: str) -> str:
    text = re.sub(r"\s+", "", message)
    if re.search(
        r"出题|出一道|出道题|出个题|考考|测试|练习|来道题|来道题目|来一道题|来一道题目|来一题|再来一道",
        text,
    ):
        return "practice"
    if re.search(r"复习|薄弱|最差|不会的", text):
        return "review_weakest"
    if re.search(r"记住|以后都|我喜欢|不要直接给答案", text):
        return "remember"
    if re.search(r"为什么|怎么做|解释|讲讲|不懂", text):
        return "explain"
    return "answer"


def _has_explicit_learning_direction(message: str) -> bool:
    """Require a clear user choice before the chat can fetch a question."""
    text = re.sub(r"\s+", "", message)
    return bool(
        re.search(
            r"出题|出一道|出道题|出个题|给我一道|给我做一道|做一道|做一题|考考我|测试我|做题|刷题|练习|练一下|来道题|来道题目|来一道题|来一道题目|再来一道|"
            r"查漏补缺|复习薄弱|复习错题|找薄弱|薄弱点|弱点|掌握情况|讲解|解释|讲讲|为什么|怎么做|怎么解",
            text,
        )
    )


def _has_explicit_practice_request(message: str) -> bool:
    text = re.sub(r"\s+", "", message)
    direct_request = bool(
        re.search(
            r"出题|出一道|出道题|出个题|给我一道|给我做一道|做一道|做一题|考考我|测试我|做题|刷题|练习|练一下|查漏补缺|来道题|来道题目|来一道题|来一道题目|来一题|再来一道",
            text,
        )
    )
    if direct_request:
        return True

    # Natural requests such as “我想做导数与微分的定义” omit the word
    # “题”, but a recognized knowledge point makes the practice intent clear.
    return bool(
        _catalog_matches(message)
        and re.search(r"想做|想练|想学做|练一练|做一下|做一遍", text)
    )


def _is_direct_learning_question(message: str) -> bool:
    """Keep ordinary knowledge questions out of the weakness-analysis route."""
    text = re.sub(r"\s+", "", message)
    if _is_weakness_analysis_request(message) or _has_explicit_practice_request(message):
        return False
    if re.search(r"最近|学习情况|掌握情况|薄弱|错题|答题记录|我的学习|哪里比较|哪里较", text):
        return False
    return bool(
        re.search(
            r"什么是|是什么|有哪些|有什么|有何|如何|怎么|为什么|区别|变化|"
            r"特点|性质|定义|公式|含义|作用|条件|方法|步骤|分类|判断",
            text,
        )
    )


def _pending_practice_intent(state: dict[str, Any]) -> str:
    """Return the unfinished practice intent from the immediately prior turn.

    A short follow-up such as ``二重积分`` is not a new conversational topic
    when the preceding user turn asked for a question and no question was
    actually produced. This is context for the Agent, not a replacement for
    its natural-language intent decision.
    """
    if state.get("current_question"):
        return ""
    messages = list(state.get("messages", []))
    last_user_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if messages[index].get("role") == "user"
        ),
        None,
    )
    if last_user_index is None:
        return ""
    previous_user_text = str(messages[last_user_index].get("content", ""))
    if not _has_explicit_practice_request(previous_user_text):
        return ""
    if any(
        item.get("role") == "assistant" and item.get("question")
        for item in messages[last_user_index + 1 :]
    ):
        return ""
    return "practice_needs_topic"


def _is_ambiguous_confusion(message: str) -> bool:
    text = re.sub(r"\s+", "", message)
    return bool(
        not _has_explicit_learning_direction(message)
        and re.search(r"不知道哪里|也不知道|不知道自己|不清楚自己|很迷茫", text)
    )


def _is_weakness_analysis_request(message: str) -> bool:
    """Detect an explicit request to inspect learning weaknesses first."""
    text = re.sub(r"\s+", "", message)
    return bool(
        re.search(
            r"(?:分析|找|查|评估|看看|判断|总结|帮我|能不能|可以).{0,12}"
            r"(?:薄弱点|弱点|哪里薄弱|哪里比较弱|哪里较弱|哪些比较弱|哪里最弱|掌握情况|错题)",
            text,
        )
        or re.search(r"(?:不知道|不清楚).*(?:哪里薄弱|哪里比较弱|弱点|掌握不好)", text)
        or re.search(r"薄弱点分析|掌握情况分析|错题分析", text)
    )


def _is_contextual_weakness_follow_up(
    state: dict[str, Any], message: str
) -> bool:
    """Recognize a short confirmation that answers the previous study choice."""
    text = re.sub(r"\s+", "", message)
    if not re.search(r"帮我分析|先分析|分析一下|分析吧|看看吧", text):
        return False
    recent_assistant_text = "".join(
        str(item.get("content", ""))
        for item in state.get("messages", [])[-4:]
        if item.get("role") == "assistant"
    )
    return bool(
        re.search(
            r"薄弱点|哪里掌握|掌握情况|学习记录|诊断题|需要加强|分析你的薄弱",
            recent_assistant_text,
        )
    )


def _has_active_learning_context(state: dict[str, Any]) -> bool:
    """Tell the safety gate whether this chat is already about studying."""
    if state.get("current_question") or state.get("weak_concepts"):
        return True
    if state.get("self_reported_concepts"):
        return True
    recent_user_text = "".join(
        str(item.get("content", ""))
        for item in state.get("messages", [])[-8:]
        if item.get("role") == "user"
    )
    return bool(
        re.search(
            r"学习|答题|题目|知识|薄弱|掌握|章节|错题|复习|练习|讲解|概念|记录|不会|哪里差",
            recent_user_text,
        )
    )


def _catalog_matches(message: str) -> list[dict[str, Any]]:
    text = re.sub(r"\s+", "", message)
    nodes = catalog_nodes()
    exact = [node for node in nodes if node["title"] in text]
    if exact:
        return sorted(exact, key=lambda node: len(node["title"]), reverse=True)
    matched: list[dict[str, Any]] = []
    for node in nodes:
        if any(len(hint) >= 4 and hint in text for hint in node["hints"]):
            matched.append(node)
    return sorted(matched, key=lambda node: len(node["title"]), reverse=True)


def _extract_self_reported_concepts(message: str) -> list[dict[str, Any]]:
    """Extract a topic the learner explicitly describes as weak or average."""
    text = re.sub(r"\s+", "", message)
    if not re.search(
        r"一般|不太好|不太会|不会|薄弱|掌握不好|不扎实|有点差|不熟|总出错|学得差",
        text,
    ):
        return []
    return _catalog_matches(message)[:2]


def _self_report_reply(concepts: list[dict[str, Any]]) -> str:
    names = "、".join(str(item["title"]) for item in concepts)
    return (
        f"明白，你觉得【{names}】目前掌握得一般。我先把它记为你的主观反馈，"
        "这还不是根据答题数据得出的结论。你想先让我讲这个知识点的核心方法，"
        "还是做一道诊断题？直接用文字告诉我你的选择就行。"
    )


def _requested_focus(
    state: dict[str, Any], message: str
) -> dict[str, Any] | None:
    matches = _catalog_matches(message)
    if matches:
        return matches[0]

    ordinal = re.search(r"第\s*(\d+)\s*个", message)
    if ordinal:
        index = int(ordinal.group(1)) - 1
        weak_concepts = state.get("weak_concepts", [])
        if 0 <= index < len(weak_concepts):
            item = weak_concepts[index]
            return {
                "id": item.get("concept_id", ""),
                "title": item.get("concept", ""),
            }

    self_reported = state.get("self_reported_concepts", [])
    if self_reported and _has_explicit_practice_request(message):
        return self_reported[0]
    return None


def _weakness_analysis_reply(
    weak_concepts: list[dict[str, Any]],
    self_reported_concepts: list[dict[str, Any]] | None = None,
) -> str:
    lines: list[str] = []
    if self_reported_concepts:
        names = "、".join(str(item["title"]) for item in self_reported_concepts)
        lines.append(
            f"你刚才主动提到：{names}学得一般。这是你的主观反馈，我会把它作为优先方向，"
            "但不会把它冒充成答题统计结果。"
        )

    if not weak_concepts:
        lines.append(
            "目前还没有足够的真实答题记录判断客观薄弱点，所以不会随便列出几个知识点。"
        )
        lines.append(
            "你可以直接说想讲哪个知识点，或者说‘给我做一道某个知识点的题’，"
            "我会按你的决定继续。"
        )
        return "\n\n".join(lines)

    lines.append("根据目前已有的答题记录，优先需要关注的是：")
    for index, item in enumerate(weak_concepts[:5], start=1):
        concept = str(item.get("concept") or item.get("topic") or "未命名知识点")
        mastery = float(item.get("mastery", 0.0))
        details = [f"掌握度约 {mastery:.0%}"]
        total_attempts = int(item.get("attempts", 0))
        if total_attempts:
            details.append(f"累计答题 {total_attempts} 次")
        attempts = int(item.get("recent_attempts", 0))
        accuracy = item.get("recent_accuracy")
        if attempts and accuracy is not None:
            details.append(f"近14天答题 {attempts} 次、正确率 {float(accuracy):.0%}")
        wrong_count = int(item.get("wrong_count", 0))
        if wrong_count:
            details.append(f"还有 {wrong_count} 次未修复的错题记录")
        lines.append(f"{index}. **{concept}**（" + "；".join(details) + "）")
    lines.append(
        "\n你可以直接回复：‘讲第1个知识点’，或者‘给我做一道第1个知识点的题’。"
        "也可以直接说出知识点名称，我按你的决定继续。"
    )
    return "\n".join(lines)


def _clarification_reply() -> str:
    return (
        "我先不急着出题。你现在还没有明确是想听讲解、分析薄弱点，还是做一道诊断题。"
        "你可以先选一种，我再根据你的决定继续，并在需要时调取合适的题目。"
    )


def _question_text(question: dict[str, Any]) -> str:
    title = (
        f"### {question.get('section_title', '固定题库题目')} · "
        f"第{question.get('question_number', '')}题"
    )
    if question.get("question_images"):
        return (
            f"{title}\n\n原题图片已准备好，请点击下方链接查看完整内容。\n\n"
            "请直接回复你的选项或解题思路。"
        )

    options = question.get("options") or []
    choices = "\n".join(
        f"{chr(65 + index)}. {option}" for index, option in enumerate(options)
    )
    return (
        f"{title}\n\n"
        f"{question.get('question_text') or question.get('question', '')}\n\n{choices}\n\n"
        "你可以直接回复你的选项或解题思路。"
    )


def _wants_question_explanation(
    state: dict[str, Any], message: str
) -> bool:
    """Recognize an explanation request while a fixed-bank question is open."""
    if not state.get("current_question"):
        return False
    text = re.sub(r"\s+", "", message)
    if re.search(r"解析|解题|解答|讲解|讲一下|为什么|怎么做|步骤|过程|答案|看懂", text):
        return True
    if len(text) <= 8 and re.search(r"^(需要|要|好|嗯|可以|行|讲吧|继续)$", text):
        recent_assistant = "".join(
            str(item.get("content", ""))
            for item in state.get("messages", [])[-4:]
            if item.get("role") == "assistant"
        )
        return bool(re.search(r"需要|进一步|解释|讲解|解题", recent_assistant))
    return False


def _fixed_question_explanation(
    question: dict[str, Any],
) -> tuple[str, list[str]] | None:
    """Return the bank-owned explanation before asking the model to explain."""
    answer_text = str(question.get("answer_text") or "").strip()
    answer_images = [str(path) for path in (question.get("answer_images") or []) if path]
    if not answer_text and not answer_images:
        return None
    if answer_text:
        reply = "这是题库中保存的固定解析：\n\n" + answer_text
    else:
        reply = "这是题库中保存的固定解析，请查看下方解析图片。"
    return reply, answer_images
def _record_chat_tool(
    state: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
    result: Any,
) -> Any:
    """Execute a chat tool and keep a compact, user-safe ReAct trace."""
    state.setdefault("tool_trace", []).append(
        {
            "tool": tool_name,
            "arguments": dict(arguments),
            "result_count": len(result) if isinstance(result, list) else int(bool(result)),
        }
    )
    return result


def _run_chat_tool(
    state: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
    *,
    trace_callback: TraceCallback | None,
    progress_callback: Callable[[str], None] | None,
) -> Any:
    """Execute one allowlisted tool while emitting call/result events."""
    _emit_chat_trace(
        state,
        trace_callback,
        progress_callback,
        "tool_call",
        tool=tool_name,
        metadata={"arguments": dict(arguments)},
    )
    started_at = perf_counter()
    try:
        result = call_agent_tool(tool_name, arguments)
    except Exception as exc:
        _emit_chat_trace(
            state,
            trace_callback,
            progress_callback,
            "error",
            status="error",
            tool=tool_name,
            message=str(exc),
            duration_ms=(perf_counter() - started_at) * 1000,
        )
        raise
    result_count = len(result) if isinstance(result, list) else int(bool(result))
    _emit_chat_trace(
        state,
        trace_callback,
        progress_callback,
        "tool_result",
        status="completed",
        tool=tool_name,
        result_count=result_count,
        duration_ms=(perf_counter() - started_at) * 1000,
    )
    _record_chat_tool(state, tool_name, arguments, result)
    return result


def _retrieve_practice_question(
    state: dict[str, Any],
    *,
    focus: dict[str, Any] | None,
    current_question_id: str,
    progress: Callable[[str], None],
    trace_callback: TraceCallback | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Run the bounded chat-page ReAct retrieval flow.

    A named focus goes straight to that knowledge node. A generic practice
    request first observes real mastery evidence, then tries the weakest
    observed nodes in order. Every question comes from the fixed bank.
    """
    excluded = [current_question_id]
    if focus:
        progress("正在从固定题库查找指定知识点")
        arguments = {"knowledge_id": str(focus["id"]), "exclude_ids": excluded}
        question = _run_chat_tool(
            state,
            "choose_question_for_knowledge",
            arguments,
            trace_callback=trace_callback,
            progress_callback=progress,
        )
        return question, []

    progress("正在读取各知识点的掌握情况")
    arguments = {"limit": 8}
    weak_concepts = _run_chat_tool(
        state,
        "get_weak_concepts",
        arguments,
        trace_callback=trace_callback,
        progress_callback=progress,
    )
    if not isinstance(weak_concepts, list):
        weak_concepts = []

    for item in weak_concepts:
        knowledge_id = str(item.get("concept_id") or "")
        if not knowledge_id:
            continue
        progress(f"正在从题库查找“{item.get('concept', '当前薄弱知识点')}”的题目")
        arguments = {"knowledge_id": knowledge_id, "exclude_ids": excluded}
        question = _run_chat_tool(
            state,
            "choose_question_for_knowledge",
            arguments,
            trace_callback=trace_callback,
            progress_callback=progress,
        )
        if question:
            return question, weak_concepts

    progress("当前没有可用的薄弱点题目，正在从固定题库选择未做题")
    arguments = {"exclude_ids": excluded}
    question = _run_chat_tool(
        state,
        "choose_daily_question",
        arguments,
        trace_callback=trace_callback,
        progress_callback=progress,
    )
    return question, weak_concepts


def _save_explicit_memory(message: str, model_memory: str = "") -> None:
    text = model_memory.strip() or message.strip()
    if not text:
        return
    key = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    save_agent_memory("conversation_preference", key, text, source="lulu_chat")


def _finish_chat_state(
    state: dict[str, Any],
    user_message: str,
    reply: str,
    action: str,
    source: str,
    current_question: dict[str, Any] | None,
    append_user: bool,
    memories: list[dict[str, Any]] | None = None,
    weak_concepts: list[dict[str, Any]] | None = None,
    self_reported_concepts: list[dict[str, Any]] | None = None,
    answer_images: list[str] | None = None,
    include_question_in_message: bool = True,
) -> dict[str, Any]:
    messages = list(state.get("messages", []))
    if append_user:
        messages.append({"role": "user", "content": user_message})
    messages.append(
        {
            "role": "assistant",
            "content": reply,
            **(
                {"question": current_question}
                if current_question and include_question_in_message
                else {}
            ),
            **({"answer_images": answer_images} if answer_images else {}),
        }
    )
    state.update(
        {
            "messages": messages[-20:],
            "current_question": current_question,
            "memories": memories if memories is not None else state.get("memories", []),
            "weak_concepts": (
                weak_concepts
                if weak_concepts is not None
                else state.get("weak_concepts", [])
            ),
            "self_reported_concepts": (
                self_reported_concepts
                if self_reported_concepts is not None
                else state.get("self_reported_concepts", [])
            ),
            "last_action": action,
            "last_decision_source": source,
        }
    )
    return state


def chat_turn(
    state: dict[str, Any],
    user_message: str,
    *,
    append_user: bool = True,
    progress_callback: Callable[[str], None] | None = None,
    trace_callback: TraceCallback | None = None,
) -> dict[str, Any]:
    def progress(stage: str) -> None:
        if progress_callback:
            progress_callback(stage)

    weak_concepts: list[dict[str, Any]] | None = None
    self_reported_concepts = _extract_self_reported_concepts(user_message)
    _emit_chat_trace(
        state,
        trace_callback,
        progress_callback,
        "route",
        message="开始解析用户请求",
    )
    progress("正在理解你的请求")
    memories = get_agent_memories(12)
    focus = _requested_focus(state, user_message)
    current_question = state.get("current_question")
    if _wants_question_explanation(state, user_message):
        fixed_explanation = _fixed_question_explanation(current_question or {})
        if fixed_explanation:
            reply, answer_images = fixed_explanation
            progress("正在读取题库中保存的固定解析")
            _emit_chat_trace(
                state,
                trace_callback,
                progress_callback,
                "response",
                status="completed",
                action="explain_fixed_question",
            )
            return _finish_chat_state(
                state,
                user_message,
                reply,
                "explain_fixed_question",
                "固定题库解析",
                current_question,
                append_user,
                memories,
                weak_concepts=state.get("weak_concepts", []),
                self_reported_concepts=state.get("self_reported_concepts", []),
                answer_images=answer_images,
                include_question_in_message=False,
            )
    explicit_weakness = _is_weakness_analysis_request(
        user_message
    ) or _is_contextual_weakness_follow_up(state, user_message)
    learning_context = _has_active_learning_context(state) or bool(
        _has_explicit_learning_direction(user_message)
    )
    explicit_practice = _has_explicit_practice_request(user_message)
    pending_practice_intent = _pending_practice_intent(state)
    direct_learning_question = _is_direct_learning_question(user_message)
    self_reported_concepts = self_reported_concepts or state.get(
        "self_reported_concepts", []
    )
    progress("正在结合最近对话理解你的问题")
    llm_started_at = perf_counter()
    _emit_chat_trace(
        state,
        trace_callback,
        progress_callback,
        "llm_call",
        metadata={"operation": "chat_agent_turn"},
    )
    tutor = AITutor()
    llm_routed = False
    try:
        if not tutor.enabled:
            raise AIServiceError("DeepSeek 暂时不可用")
        planner_args = {
            "user_message": user_message,
            "weak_concepts": weak_concepts or [],
            "memories": memories,
            "dialogue": state.get("messages", []),
            "focus_concepts": [focus] if focus else [],
            "request_context": {
                "self_reported_topic": bool(self_reported_concepts),
                "active_learning_context": learning_context,
                "has_current_question": bool(state.get("current_question")),
                "pending_practice_intent": pending_practice_intent,
                "direct_learning_question": direct_learning_question,
                "current_question": (
                    {
                        "id": current_question.get("id"),
                        "section_title": current_question.get("section_title"),
                        "question_text": current_question.get("question_text"),
                        "answer_text": current_question.get("answer_text"),
                        "answer_choice": current_question.get("answer_choice"),
                    }
                    if isinstance(current_question, dict)
                    else None
                ),
            },
            "available_tools": (
                [] if direct_learning_question else agent_tool_catalog()
            ),
        }
        agent_loop = getattr(tutor, "chat_agent_loop", None)
        if callable(agent_loop):
            def execute_agent_tool(name: str, arguments: dict[str, Any]) -> Any:
                state.setdefault("llm_tool_requests", []).append(
                    {"tool": name, "arguments": dict(arguments)}
                )
                _emit_chat_trace(
                    state,
                    trace_callback,
                    progress_callback,
                    "tool_request",
                    status="planned",
                    tool=name,
                    metadata={"arguments": dict(arguments)},
                )
                return _run_chat_tool(
                    state,
                    name,
                    arguments,
                    trace_callback=trace_callback,
                    progress_callback=progress,
                )

            try:
                decision = agent_loop(
                    **planner_args,
                    tool_executor=execute_agent_tool,
                )
                if (
                    (explicit_practice or (pending_practice_intent and focus))
                    and not decision.get("tool_results")
                ):
                    # A clear request for a question is a contract the final
                    # answer must satisfy. Ask the same Agent again with a
                    # required native tool call instead of showing a prose
                    # acknowledgement as if it were the result.
                    progress("正在确认调用固定题库工具")
                    decision = agent_loop(
                        **planner_args,
                        tool_executor=execute_agent_tool,
                        force_tool_on_first_step=True,
                    )
            except AIServiceError:
                # Keep the provider-compatible JSON route as a second LLM
                # path before falling all the way back to local handling.
                decision = tutor.chat_agent_turn(**planner_args)
        else:
            # Compatibility path for providers without native tool calls and
            # for the validated JSON router used by the fallback tests.
            decision = tutor.chat_agent_turn(**planner_args)
        llm_routed = True
        source = "DeepSeek 自然语言路由"
        planned_tool = decision.get("tool_name")
        if planned_tool and not decision.get("tool_results"):
            state.setdefault("llm_tool_requests", []).append(
                {
                    "tool": planned_tool,
                    "arguments": dict(decision.get("tool_arguments") or {}),
                }
            )
            _emit_chat_trace(
                state,
                trace_callback,
                progress_callback,
                "tool_request",
                status="planned",
                tool=str(planned_tool),
                metadata={"arguments": dict(decision.get("tool_arguments") or {})},
            )
        _emit_chat_trace(
            state,
            trace_callback,
            progress_callback,
            "llm_result",
            status="completed",
            action=str(decision.get("next_action", "answer")),
            duration_ms=(perf_counter() - llm_started_at) * 1000,
        )
    except AIServiceError:
        _emit_chat_trace(
            state,
            trace_callback,
            progress_callback,
            "error",
            status="error",
            message="LLM 路由暂时不可用",
            duration_ms=(perf_counter() - llm_started_at) * 1000,
        )
        progress("噜噜暂时无法连接，正在使用本地安全处理流程")
        if explicit_weakness:
            fallback_reply = _weakness_analysis_reply(
                weak_concepts or [], self_reported_concepts
            )
            fallback_action = "review_weakest"
        elif self_reported_concepts:
            fallback_reply = _self_report_reply(self_reported_concepts)
            fallback_action = "answer"
        elif explicit_practice or (pending_practice_intent and focus):
            fallback_reply = "我来按你指定的方向查找固定题库题目。"
            fallback_action = "practice"
        elif _is_ambiguous_confusion(user_message):
            fallback_reply = _clarification_reply()
            fallback_action = "clarify"
        else:
            fallback_reply = "我听到了。你可以继续说，我会先理解你的意思，再决定是否需要结合学习记录。"
            fallback_action = "answer"
        decision = {
            "reply": fallback_reply,
            "next_action": fallback_action,
            "memory": "",
            "target_knowledge_id": None,
        }
        source = "本地自然语言路由（DeepSeek 暂时不可用）"

    progress("正在确认这次请求的处理方向")
    action = decision["next_action"]
    reply = decision["reply"]
    planned_tool = str(decision.get("tool_name") or "")
    loop_question: dict[str, Any] | None = None
    loop_results = decision.get("tool_results") or []
    if isinstance(loop_results, list):
        for observation in loop_results:
            if not isinstance(observation, dict):
                continue
            tool_name = str(observation.get("tool") or "")
            result = observation.get("result")
            if tool_name == "get_weak_concepts" and isinstance(result, list):
                weak_concepts = result
            if tool_name in {
                "choose_daily_question",
                "choose_question_for_knowledge",
                "search_prerequisite_questions",
                "search_same_section_questions",
            }:
                if isinstance(result, dict):
                    loop_question = result
                elif isinstance(result, list) and result and isinstance(result[0], dict):
                    loop_question = result[0]
    model_requested_weakness = (
        action == "review_weakest" and planned_tool == "get_weak_concepts"
    )
    if not llm_routed and (explicit_practice or (pending_practice_intent and focus)):
        action = "practice"
    elif not llm_routed and explicit_weakness:
        action = "review_weakest"
    elif (
        not llm_routed and action in {"practice", "review_weakest"}
        and not _has_explicit_learning_direction(user_message)
        and not model_requested_weakness
        and not (action == "review_weakest" and learning_context)
    ):
        # The model may misclassify an off-topic message. Prevent a tool call,
        # but keep its natural answer instead of replacing it with a study menu.
        # A validated get_weak_concepts request is different: it may be a
        # contextual follow-up such as "帮我分析" after the user already said
        # they do not know where they are weak.
        action = "answer"
    if action == "review_weakest":
        progress("正在根据答题记录整理薄弱点分析")
        if weak_concepts is None:
            weak_concepts = _run_chat_tool(
                state,
                "get_weak_concepts",
                {"limit": 8},
                trace_callback=trace_callback,
                progress_callback=progress,
            )
        # A native tool call may carry a short acknowledgement such as
        # "我先分析一下". That is progress, not the final answer. Once the
        # real mastery tool has run, show its data-backed summary instead.
        if not llm_routed or planned_tool == "get_weak_concepts" or not reply.strip():
            reply = _weakness_analysis_reply(
                weak_concepts or [], self_reported_concepts
            )
        _emit_chat_trace(
            state,
            trace_callback,
            progress_callback,
            "response",
            status="completed",
            action="analyze_weakness",
        )
        return _finish_chat_state(
            state,
            user_message,
            reply or _weakness_analysis_reply(weak_concepts, self_reported_concepts),
            "analyze_weakness",
            source,
            None,
            append_user,
            weak_concepts=weak_concepts,
            self_reported_concepts=self_reported_concepts,
        )
    current_question = None
    if action == "practice":
        practice_weak_concepts = weak_concepts or []
        current_question = loop_question
        if current_question is None:
            current_question_id = (state.get("current_question") or {}).get("id", "")
            current_question, practice_weak_concepts = _retrieve_practice_question(
                state,
                focus=focus,
                current_question_id=current_question_id,
                progress=progress,
                trace_callback=trace_callback,
            )
        if practice_weak_concepts:
            weak_concepts = practice_weak_concepts
        if current_question:
            reply = _question_text(current_question)
        elif focus:
            reply = (
                f"我没有在固定题库里找到与“{focus.get('title', '这个知识点')}”严格匹配的题目，"
                "所以没有换成其他章节。你可以让我先讲这个知识点，或者换一个更具体的题型。"
            )
        else:
            reply = "固定题库暂时没有找到合适的未做题，我们先聊聊你具体卡在哪里。"
    elif action == "remember":
        progress("正在整理并保存你希望噜噜记住的内容")
        _save_explicit_memory(user_message, decision.get("memory", ""))
    else:
        progress("正在组织与你当前问题相关的回复")

    if current_question is None and action in {"answer", "explain", "remember"}:
        # Keep the active question available for a follow-up such as
        # "需要" after Lulu offered to provide the explanation. Do not attach
        # the question card again; it has already been shown in the chat.
        current_question = state.get("current_question")

    progress("正在整理回复")
    _emit_chat_trace(
        state,
        trace_callback,
        progress_callback,
        "response",
        status="completed",
        action=action,
    )
    memories = get_agent_memories(12)
    if action != "remember" and decision.get("memory"):
        _save_explicit_memory(user_message, decision["memory"])
    return _finish_chat_state(
        state,
        user_message,
        reply,
        action,
        source,
        current_question,
        append_user,
        memories,
        weak_concepts=weak_concepts,
        self_reported_concepts=self_reported_concepts,
    )
