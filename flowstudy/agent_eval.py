"""Small, deterministic checks for the learning Agent contract.

The cases do not call a paid model. They validate the boundary that must remain
true even when a provider is unavailable: allowed actions, tool routing and
question-source safety.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flowstudy.react_agent import ACTION_TOOL_MAP, AGENT_TOOL_REGISTRY


CASES_PATH = Path(__file__).resolve().parent.parent / "data" / "agent_eval_cases.json"


def load_eval_cases() -> list[dict[str, Any]]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def evaluate_agent_decision(
    decision: dict[str, Any],
    expected_action: str,
    expected_tool: str,
) -> dict[str, Any]:
    """Evaluate one already-produced model decision without executing a tool."""
    action = str(decision.get("next_action", ""))
    selected_tool = str(
        decision.get("tool_name") or ACTION_TOOL_MAP.get(action, "diagnose_question")
    )
    valid_action = action in {
        "ask_clarification",
        "explain",
        "practice_prerequisite",
        "practice_same_section",
        "verify_original",
        "finish",
    }
    valid_tool = selected_tool in {
        "diagnose_question",
        "verify_original",
    } or selected_tool in AGENT_TOOL_REGISTRY
    return {
        "passed": valid_action and valid_tool and action == expected_action and selected_tool == expected_tool,
        "action": action,
        "tool": selected_tool,
        "valid_action": valid_action,
        "valid_tool": valid_tool,
    }


def evaluate_cases(decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    results = []
    for case in load_eval_cases():
        decision = decisions.get(case["id"], {})
        result = evaluate_agent_decision(
            decision,
            case["expected_action"],
            case["expected_tool"],
        )
        results.append({"id": case["id"], **result})
    passed = sum(1 for item in results if item["passed"])
    return {
        "passed": passed,
        "total": len(results),
        "accuracy": passed / len(results) if results else 0.0,
        "results": results,
    }
