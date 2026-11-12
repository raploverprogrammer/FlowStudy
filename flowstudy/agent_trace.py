"""User-safe execution events for observable Agent progress.

These events describe application actions, not the model's hidden chain of
thought. The UI can render them while developers can retain the structured
fields for debugging and evaluation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def make_trace_event(
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
    """Create a serializable event describing one observable Agent step."""
    event: dict[str, Any] = {
        "event_type": event_type,
        "status": status,
        "tool": tool,
        "action": action,
        "message": message,
        "created_at": datetime.now().isoformat(timespec="milliseconds"),
    }
    if result_count is not None:
        event["result_count"] = int(result_count)
    if duration_ms is not None:
        event["duration_ms"] = round(float(duration_ms), 2)
    if metadata:
        event["metadata"] = dict(metadata)
    return event


def trace_to_progress(event: dict[str, Any]) -> str:
    """Translate an execution event into a concise learner-facing status."""
    event_type = str(event.get("event_type", ""))
    status = str(event.get("status", ""))
    tool = str(event.get("tool", ""))
    action = str(event.get("action", ""))
    result_count = event.get("result_count")

    if event_type == "route":
        return "正在判断如何处理你的问题"
    if event_type == "llm_call":
        return "正在请噜噜结合对话理解你的问题"
    if event_type == "llm_result":
        return f"噜噜已确定处理方向：{action or '继续对话'}"
    if event_type == "tool_request":
        return "正在根据你的表达选择需要的学习工具"
    if event_type == "tool_call":
        labels = {
            "get_weak_concepts": "正在查看你的知识点掌握情况",
            "choose_question_for_knowledge": "正在从题库查找对应知识点的题目",
            "choose_daily_question": "正在从固定题库筛选合适的题目",
        }
        return labels.get(tool, f"正在调用学习工具：{tool}")
    if event_type == "tool_result":
        if tool == "get_weak_concepts":
            count = result_count or 0
            return f"已读取掌握情况，找到 {count} 个有真实记录的薄弱方向"
        if tool == "choose_question_for_knowledge":
            return "已找到匹配的固定题库题目"
        if tool == "choose_daily_question":
            return "已从固定题库筛选出题目"
        return event.get("message") or "学习工具已返回结果"
    if event_type == "response":
        return "正在整理最终回复"
    if event_type == "error" or status == "error":
        return "这一步遇到问题，正在准备可用的兜底回复"
    return event.get("message") or "正在处理你的请求"
