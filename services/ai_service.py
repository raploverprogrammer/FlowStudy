from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable
from uuid import uuid4

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-chat"
SESSION_QUESTION_COUNT = 5

SYSTEM_PROMPT = """
你是 FlowStudy 的 AI 导师「噜噜导师」。

你的任务是帮助中国考研学生通过高质量题目掌握考研数学概率论。

教学规则：
1. 严格围绕当前 Topic 和知识点，禁止脱离给定 Topic Tree。
2. 优先使用你能够明确确认出处的考研真题。只有明确知道年份和题型时才能标注
   “考研真题”；不能确认出处时，必须标注“考研真题风格”，不得虚构真题来源。
3. 不要出儿童题、常识题或送分题，题目应具有真实考研区分度。
4. 不要长篇讲课，优先通过题目发现认知漏洞。
5. 用户答错时，先指出错误类型和思路漏洞，通过一个简短追问帮助用户发现问题，
   再做简短讲解，然后进入下一题。
6. 一次学习固定 5 题，不得无限对话。
7. 第 5 题结束后必须停止出题，并根据正确题数评级。
8. 所有输出使用简体中文，公式使用 Markdown LaTeX。

评级规则：
5/5 = ⭐ 传奇发现者
4/5 = 🌊 深海探索者
3/5 = ⛵ 熟练航海家
2/5 = 🌿 见习探索者
0~1/5 = 🌱 萌芽航海员
""".strip()


class AIServiceError(RuntimeError):
    """A readable error raised when the AI provider cannot serve a request."""


class AITutor:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.model = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
        self.client = client
        if self.client is None and self.api_key:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=OPENROUTER_BASE_URL,
                default_headers={
                    "HTTP-Referer": "http://localhost:8501",
                    "X-Title": "FlowStudy",
                },
                timeout=45.0,
                max_retries=0,
            )

    @staticmethod
    def _clean_protocol_text(text: str, fallback: str) -> str:
        """Keep accidental tool-protocol fragments out of learner replies."""
        value = str(text or "").strip()
        if re.search(r"(?is)\bjson\b.*[\"']question_id[\"']\s*:", value):
            return fallback
        return value or fallback

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.client)

    def _require_client(self) -> OpenAI:
        if not self.enabled:
            raise AIServiceError(
                "未配置 OPENROUTER_API_KEY。请在项目根目录的 .env 中填写后重启应用。"
            )
        return self.client  # type: ignore[return-value]

    def _json_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.35,
        max_tokens: int = 1600,
        json_mode: bool = True,
    ) -> dict[str, Any]:
        for attempt in range(3):
            try:
                request = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if json_mode:
                    request["response_format"] = {"type": "json_object"}
                response = self._require_client().chat.completions.create(**request)
                content = response.choices[0].message.content or ""
                cleaned = content.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned.removeprefix("```json").strip()
                if cleaned.endswith("```"):
                    cleaned = cleaned.removesuffix("```").strip()
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    start = cleaned.find("{")
                    end = cleaned.rfind("}")
                    if start >= 0 and end > start:
                        return json.loads(cleaned[start : end + 1])
                    raise
            except AIServiceError:
                raise
            except (json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
                raise AIServiceError("噜噜导师返回的数据格式不完整，请稍后重试。") from exc
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                is_rate_limited = status_code == 429 or "429" in str(exc)
                if is_rate_limited and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise AIServiceError(f"OpenRouter 调用失败：{exc}") from exc

    def _text_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.35,
        max_tokens: int = 800,
    ) -> str:
        """Request ordinary prose for learner-facing messages."""
        for attempt in range(3):
            try:
                response = self._require_client().chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = (response.choices[0].message.content or "").strip()
                if not content:
                    raise AIServiceError("噜噜导师没有返回有效的引导内容，请稍后重试。")
                return content
            except AIServiceError:
                raise
            except (IndexError, KeyError, TypeError) as exc:
                raise AIServiceError("噜噜导师没有返回有效的引导内容，请稍后重试。") from exc
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                is_rate_limited = status_code == 429 or "429" in str(exc)
                if is_rate_limited and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise AIServiceError(f"OpenRouter 调用失败：{exc}") from exc

    @staticmethod
    def _context_payload(
        context: dict[str, Any],
        recent_dialogue: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        return {
            "current_topic": context["topic"],
            "current_concept": context["breadcrumb"],
            "current_mastery": context.get("mastery", 0.0),
            "current_rank": context.get("rank", "🌱 萌芽航海员"),
            "current_weakness": context.get("weakness", "尚未发现明确漏洞"),
            "chapter_core_concepts": context.get("core_concepts", []),
            "chapter_high_frequency_points": context.get(
                "high_frequency_points", []
            ),
            "recent_dialogue": (recent_dialogue or [])[-10:],
        }

    @staticmethod
    def _normalize_question(
        value: Any,
        concept_name: str,
        question_number: int,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise AIServiceError("噜噜导师没有生成有效题目，请重试。")
        required = {"question", "options", "answer", "explanation"}
        if not required.issubset(value):
            raise AIServiceError("AI 题目缺少题干、选项、答案或解析。")
        options = value["options"]
        answers = value["answer"]
        if (
            not isinstance(options, list)
            or len(options) < 2
            or not isinstance(answers, list)
            or not answers
        ):
            raise AIServiceError("AI 题目的选项或答案格式不正确。")
        normalized_answers = [int(index) for index in answers]
        if min(normalized_answers) < 0 or max(normalized_answers) >= len(options):
            raise AIServiceError("AI 题目的正确答案索引越界。")
        return {
            "id": f"openrouter-{uuid4().hex}",
            "phase": "tutor",
            "type": str(value.get("type", "single")),
            "knowledge_point": concept_name,
            "question_number": question_number,
            "source_type": str(value.get("source_type", "考研真题风格")),
            "source_note": str(value.get("source_note", "")),
            "question": str(value["question"]),
            "options": [str(option) for option in options],
            "answer": normalized_answers,
            "explanation": str(value["explanation"]),
        }

    def test_connection(self) -> bool:
        try:
            response = self._require_client().chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "只回复 OK"}],
                temperature=0,
                max_tokens=8,
            )
            return bool(response.choices and response.choices[0].message.content)
        except AIServiceError:
            raise
        except Exception as exc:
            raise AIServiceError(f"OpenRouter 连接失败：{exc}") from exc

    def explain_question(
        self,
        *,
        section_title: str,
        question_text: str,
        answer_text: str = "",
        user_question: str = "",
        recent_dialogue: list[dict[str, str]] | None = None,
    ) -> str:
        dialogue = (recent_dialogue or [])[-10:]
        context = f"""
当前章节：{section_title}

当前题目 OCR 文本：
{question_text or "题目以扫描图片展示，OCR 文本不完整。"}

题库参考答案：
{answer_text or "参考答案以解析图片为准。"}
""".strip()
        system_prompt = """
你是 FlowStudy 的考研数学导师「噜噜」。
你正在围绕同一道题与用户连续对话，不是一次性输出标准答案。

规则：
1. 紧扣当前题目和用户这一次具体疑问；
2. 结合最近对话继续讲，不重复已经讲清的整段内容；
3. 优先定位用户卡住的条件、概念或推理步骤，再由浅入深解释；
4. 不要只丢出答案。必要时用一个简短问题确认用户是否理解；
        5. 使用简体中文和 Markdown，完整回答，不要因为篇幅限制截断；内容较长时分段说明；
6. 不得编造题目中没有的条件；OCR 不完整时明确提醒以扫描原题为准。
""".strip()
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
            {
                "role": "assistant",
                "content": "我会始终围绕这道题，根据你的具体疑问继续讲解。",
            },
        ]
        for item in dialogue:
            role = item.get("role")
            content = str(item.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append(
            {
                "role": "user",
                "content": user_question.strip()
                or "请先帮我判断这道题最关键的解题入口。",
            }
        )
        try:
            response = self._require_client().chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
                max_tokens=1800,
            )
            return (response.choices[0].message.content or "").strip()
        except AIServiceError:
            raise
        except Exception as exc:
            raise AIServiceError(f"OpenRouter 调用失败：{exc}") from exc

    def _chat_agent_turn_native(
        self,
        *,
        user_message: str,
        weak_concepts: list[dict[str, Any]],
        memories: list[dict[str, Any]],
        dialogue: list[dict[str, str]],
        focus_concepts: list[dict[str, Any]] | None,
        request_context: dict[str, Any] | None,
        available_tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Route chat with real OpenAI-compatible tool calls when available."""
        native_tools = [
            {"type": "function", "function": tool}
            for tool in available_tools
            if isinstance(tool, dict) and tool.get("name")
        ]
        tool_names = {str(tool["function"]["name"]) for tool in native_tools}
        payload = {
            "user_message": user_message,
            "weak_concepts": weak_concepts[:8],
            "selected_focus": (focus_concepts or [])[:3],
            "request_context": request_context or {},
            "learning_memories": [
                {"type": item.get("memory_type"), "content": item.get("content")}
                for item in memories[:12]
            ],
            "recent_dialogue": dialogue[-10:],
        }
        try:
            response = self._require_client().chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是 FlowStudy 的噜噜学习 Agent。理解完整对话后决定下一步。"
                            "需要读取学习记录或题库时，必须直接调用合适的工具；不要只说‘我去查询’。"
                            "用户的表达不固定，必须根据语义和上下文判断，不要求关键词。"
                            "只想知道薄弱点、掌握情况或答题记录时调用 get_weak_concepts；"
                            "如果用户说查漏补缺、找薄弱处巩固、按短板练习、补齐不会的内容，"
                            "这是先分析掌握情况再练一道题的练习请求，应调用 choose_daily_question，"
                            "不要只调用 get_weak_concepts，也不要只回复准备语句。"
                            "get_learning_memories 只在用户明确要求记住或回忆偏好时调用。"
                            "离题闲聊不要调用学习工具；不要生成题目，题目只能来自固定题库工具。"
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                tools=native_tools,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=1200,
            )
        except AIServiceError:
            raise
        except Exception as exc:
            raise AIServiceError(f"OpenRouter 原生工具调用失败：{exc}") from exc
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise AIServiceError("噜噜原生工具调用没有返回消息，请改用普通路由重试。")
        message = getattr(choices[0], "message", None)
        if message is None:
            raise AIServiceError("噜噜原生工具调用返回了空消息，请改用普通路由重试。")
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            call = tool_calls[0]
            function = getattr(call, "function", None)
            name = str(getattr(function, "name", ""))
            if function is None or not name:
                raise AIServiceError("噜噜返回的工具调用不完整，请改用普通路由重试。")
            if name not in tool_names:
                raise AIServiceError(f"噜噜请求了未注册的工具：{name}")
            try:
                arguments = json.loads(function.arguments or "{}")
            except json.JSONDecodeError as exc:
                raise AIServiceError("噜噜返回的工具参数格式不完整，请稍后重试。") from exc
            if not isinstance(arguments, dict):
                raise AIServiceError("噜噜返回的工具参数不是对象，请稍后重试。")
            action = {
                "get_weak_concepts": "review_weakest",
                "choose_daily_question": "practice",
                "choose_question_for_knowledge": "practice",
            }.get(name, "answer")
            tool_reply = str(getattr(message, "content", None) or "").strip()
            if not tool_reply:
                tool_reply = {
                    "get_weak_concepts": "我先根据你的答题记录分析薄弱点。",
                    "choose_daily_question": "我先从固定题库里挑一道合适的题。",
                    "choose_question_for_knowledge": "我先从固定题库里查找对应知识点的题目。",
                }.get(name, "我先读取相关学习数据，再继续回答你。")
            return {
                "reply": tool_reply,
                "next_action": action,
                "memory": "",
                "target_knowledge_id": arguments.get("knowledge_id"),
                "tool_name": name,
                "tool_arguments": arguments,
                "tool_call_id": str(getattr(call, "id", "chat-tool-call-1")),
            }
        return {
            "reply": str(getattr(message, "content", None) or "你可以继续告诉我你的想法。"),
            "next_action": "answer",
            "memory": "",
            "target_knowledge_id": None,
            "tool_name": None,
            "tool_arguments": {},
        }

    def chat_agent_loop(
        self,
        *,
        user_message: str,
        weak_concepts: list[dict[str, Any]],
        memories: list[dict[str, Any]],
        dialogue: list[dict[str, str]],
        focus_concepts: list[dict[str, Any]] | None = None,
        request_context: dict[str, Any] | None = None,
        available_tools: list[dict[str, Any]],
        tool_executor: Callable[[str, dict[str, Any]], Any],
        max_steps: int = 6,
        force_tool_on_first_step: bool = False,
    ) -> dict[str, Any]:
        """Run the open-ended chat Agent Loop.

        The model chooses whether to stop or call another registered tool
        after each observation. The application owns execution and safety;
        the model owns the next-step decision.
        """
        native_tools = [
            {"type": "function", "function": tool}
            for tool in available_tools
            if isinstance(tool, dict) and tool.get("name")
        ]
        tool_names = {str(tool["function"]["name"]) for tool in native_tools}
        payload = {
            "user_message": user_message,
            "weak_concepts": weak_concepts[:8],
            "selected_focus": (focus_concepts or [])[:3],
            "request_context": request_context or {},
            "learning_memories": [
                {"type": item.get("memory_type"), "content": item.get("content")}
                for item in memories[:12]
            ],
            "recent_dialogue": dialogue[-10:],
        }
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "你是 FlowStudy 的噜噜学习 Agent。根据用户原话和完整对话判断意图。"
                    "每次收到工具结果后重新判断下一步；如果信息已经足够就停止调用工具并回答。"
                    "只想了解薄弱点时调用 get_weak_concepts。"
                    "如果 request_context.direct_learning_question 为 true，用户是在询问知识内容，"
                    "直接围绕问题回答，不要调用薄弱点或题库工具。"
                    "想查漏补缺、按薄弱点练习或补齐不会的内容时，先在需要时读取掌握情况，"
                    "再调用固定题库工具选择题目，不要生成题目。"
                    "用户说出题、出道题、来一道、考考我、做题或再来一道时，不能只用文字答复，"
                    "必须调用题库工具；如果没有指定知识点，就调用 choose_daily_question。"
                    "如果上一轮已经表达了出题或练题意图，而本轮只补充一个知识点名称，"
                    "必须继承上一轮意图，把这个名称当作题库检索参数，调用 choose_question_for_knowledge；"
                    "不要把它当成新的闲聊，也不要再次只回复确认性话术。"
                    "与学习无关的闲聊不要调用学习工具。用户表达不需要包含固定关键词。"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        tool_results: list[dict[str, Any]] = []
        last_tool_name = ""
        last_tool_arguments: dict[str, Any] = {}
        try:
            for _ in range(max(1, max_steps)):
                response = self._require_client().chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=native_tools,
                    tool_choice=(
                        "required"
                        if force_tool_on_first_step and not tool_results
                        else "auto"
                    ),
                    temperature=0.2,
                    max_tokens=1200,
                )
                choices = getattr(response, "choices", None) or []
                if not choices:
                    raise AIServiceError("噜噜 Agent 没有返回下一步决策。")
                message = getattr(choices[0], "message", None)
                if message is None:
                    raise AIServiceError("噜噜 Agent 返回了空决策。")
                calls = getattr(message, "tool_calls", None) or []
                if not calls:
                    reply = str(getattr(message, "content", None) or "").strip()
                    question_tools = {
                        "choose_daily_question",
                        "choose_question_for_knowledge",
                        "search_prerequisite_questions",
                        "search_same_section_questions",
                    }
                    if any(item["tool"] in question_tools for item in tool_results):
                        action = "practice"
                    elif any(item["tool"] == "get_weak_concepts" for item in tool_results):
                        action = "review_weakest"
                    else:
                        action = "answer"
                    return {
                        "reply": reply or "你可以继续告诉我想解决的学习问题。",
                        "next_action": action,
                        "memory": "",
                        "target_knowledge_id": last_tool_arguments.get("knowledge_id"),
                        "tool_name": last_tool_name or None,
                        "tool_arguments": last_tool_arguments,
                        "tool_results": tool_results,
                    }

                assistant_calls: list[dict[str, Any]] = []
                for call in calls:
                    function = getattr(call, "function", None)
                    name = str(getattr(function, "name", ""))
                    if function is None or name not in tool_names:
                        raise AIServiceError(f"噜噜请求了未注册的工具：{name}")
                    try:
                        arguments = json.loads(getattr(function, "arguments", "{}") or "{}")
                    except json.JSONDecodeError as exc:
                        raise AIServiceError("噜噜返回的工具参数格式不完整。") from exc
                    if not isinstance(arguments, dict):
                        raise AIServiceError("噜噜返回的工具参数不是对象。")
                    call_id = str(getattr(call, "id", f"chat-tool-call-{len(tool_results) + 1}"))
                    assistant_calls.append(
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments, ensure_ascii=False),
                            },
                        }
                    )
                    last_tool_name = name
                    last_tool_arguments = arguments
                    result = tool_executor(name, arguments)
                    tool_results.append(
                        {"tool": name, "arguments": arguments, "result": result}
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": name,
                            "content": json.dumps(result, ensure_ascii=False, default=str)[:6000],
                        }
                    )
                messages.insert(
                    -len(calls),
                    {
                        "role": "assistant",
                        "content": getattr(message, "content", None),
                        "tool_calls": assistant_calls,
                    },
                )
            raise AIServiceError("噜噜 Agent 达到本轮工具调用上限。")
        except AIServiceError:
            raise
        except Exception as exc:
            raise AIServiceError(f"OpenRouter Agent Loop 调用失败：{exc}") from exc

    def chat_agent_turn(
        self,
        *,
        user_message: str,
        weak_concepts: list[dict[str, Any]],
        memories: list[dict[str, Any]],
        dialogue: list[dict[str, str]],
        focus_concepts: list[dict[str, Any]] | None = None,
        request_context: dict[str, Any] | None = None,
        available_tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Route an open-ended Lulu conversation to a safe learning action."""
        tools = available_tools or []
        if tools:
            try:
                return self._chat_agent_turn_native(
                    user_message=user_message,
                    weak_concepts=weak_concepts,
                    memories=memories,
                    dialogue=dialogue,
                    focus_concepts=focus_concepts,
                    request_context=request_context,
                    available_tools=tools,
                )
            except AIServiceError:
                # Some OpenAI-compatible providers/models do not implement
                # function calling. Keep the validated JSON route as fallback.
                pass
        payload = {
            "user_message": user_message,
            "weak_concepts": weak_concepts[:8],
            "selected_focus": (focus_concepts or [])[:3],
            "request_context": request_context or {},
            "learning_memories": [
                {"type": item.get("memory_type"), "content": item.get("content")}
                for item in memories[:12]
            ],
            "recent_dialogue": dialogue[-10:],
            "available_tools": available_tools or [],
            "allowed_actions": [
                "answer",
                "explain",
                "practice",
                "review_weakest",
                "clarify",
                "remember",
            ],
            "requirements": [
                "用户明确要求出题、考考我或练习时选择 practice；绝对不要在 reply 中自行编写题目，应用会先读取掌握证据，再从固定题库取题",
                "用户明确说出知识点时，target_knowledge_id 只能填写给定知识点；没有明确知识点时不要猜一个知识点，应用会按掌握度选择",
                "request_context.direct_learning_question 为 true 时，直接回答知识问题，不调用学习记录或题库工具",
                "practice 的 reply 只说明正在按掌握情况从固定题库取题，不要假装题目已经由你生成",
                "先判断用户是在聊学习，还是在表达情绪、闲聊或询问与学习无关的内容",
                "如果用户没有把话题和学习联系起来，就自然回应，不要硬扯薄弱点、题目或学习计划",
                "用户询问概念或解法时选择 explain 或 answer",
                "用户明确要求分析薄弱点时必须选择 review_weakest，只能依据 weak_concepts 和 selected_focus，不要编造统计结论",
                "查漏补缺、找薄弱处巩固、按短板练习等表达，表示先读取掌握情况再从固定题库取一道题，应选择 practice 并请求题库工具，不要只回复‘稍等’",
                "用户已经按知识点名称或列表序号做出选择时，必须围绕 selected_focus 回复，不要改换成其他知识点",
                "用户只说不知道哪里不懂、很迷茫或没有明确学习方式时选择 clarify，先询问用户想讲解、分析薄弱点还是做诊断题，不要调用题目",
                "只有用户明确要求记住偏好时才选择 remember",
                "available_tools 是当前应用真实提供的工具目录；需要读取学习数据或题库时，先在 tool_name 中选择目录里的工具并填写合法参数",
                "不要编造工具名、参数或工具结果；不需要工具时 tool_name 必须为 null，tool_arguments 必须为空对象",
                "tool_name 只是给应用的工具请求，应用会再次校验并决定实际执行；不要在 reply 中声称工具已经执行",
                "reply 使用简体中文，完整回答当前问题；内容较长时分段，不要在步骤中途截断",
            ],
            "output_schema": {
                "reply": "给用户看的回复",
                "next_action": "answer|explain|practice|review_weakest|clarify|remember",
                "memory": "需要保存的简短用户偏好，没有则为空",
                "target_knowledge_id": "用户明确指定或你判断应练习的知识点 id，没有则为 null",
                "tool_name": "从 available_tools 中选择一个工具名，不需要工具时为 null",
                "tool_arguments": "该工具的 JSON 参数对象，不需要工具时为空对象",
            },
        }
        data = self._json_completion(
            [
                {
                    "role": "system",
                    "content": "你是 FlowStudy 的噜噜学习 Agent，负责把自然语言请求路由到合适的学习动作。",
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.2,
            max_tokens=1200,
            json_mode=False,
        )
        allowed = {
            "answer",
            "explain",
            "practice",
            "review_weakest",
            "clarify",
            "remember",
        }
        action = str(data.get("next_action", "answer"))
        if action not in allowed:
            action = "answer"
        available_names = {
            str(tool.get("name"))
            for tool in (available_tools or [])
            if isinstance(tool, dict) and tool.get("name")
        }
        tool_name = data.get("tool_name")
        if tool_name not in available_names:
            tool_name = None
        if tool_name is None and action == "review_weakest" and "get_weak_concepts" in available_names:
            # The action itself is already an unambiguous request to inspect
            # mastery. This keeps the router robust when a provider omits the
            # optional tool_name field from otherwise valid JSON.
            tool_name = "get_weak_concepts"
        tool_arguments = data.get("tool_arguments")
        if not isinstance(tool_arguments, dict):
            tool_arguments = {}
        return {
            "reply": str(data.get("reply") or "你可以告诉我想解释、练习还是复习哪一部分。"),
            "next_action": action,
            "memory": str(data.get("memory", "")).strip(),
            "target_knowledge_id": data.get("target_knowledge_id"),
            "tool_name": tool_name,
            "tool_arguments": tool_arguments,
        }

    def diagnose_question_turn(
        self,
        *,
        question: dict[str, Any],
        original_user_answer: str,
        user_message: str,
        knowledge_tags: list[dict[str, Any]],
        section_mastery: dict[str, Any],
        weak_prerequisites: list[dict[str, Any]],
        prerequisite_mastery: list[dict[str, Any]],
        dialogue: list[dict[str, str]],
        support_results: list[dict[str, Any]],
        memory_context: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Choose the next bounded action in the daily-question diagnosis chat."""
        payload = {
            "question": {
                "section_title": question.get("section_title", ""),
                "question_text": str(question.get("question_text", ""))[:1800],
                "reference_answer": question.get("answer_text", "") or question.get(
                    "answer_choice", ""
                ),
            },
            "original_user_answer": original_user_answer,
            "user_message": user_message,
            "knowledge_tags": [
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "relation": item.get("relation"),
                }
                for item in knowledge_tags
            ],
            "section_mastery": section_mastery,
            "weak_prerequisites": [
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "mastery": item.get("mastery", {}),
                }
                for item in weak_prerequisites
            ],
            "prerequisite_mastery": [
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "mastery": item.get("mastery", {}),
                }
                for item in prerequisite_mastery
            ],
            "support_results": support_results[-3:],
            "learning_memories": [
                {
                    "type": item.get("memory_type"),
                    "content": item.get("content"),
                }
                for item in (memory_context or [])[:12]
            ],
            "recent_dialogue": dialogue[-8:],
            "allowed_actions": [
                "ask_clarification",
                "explain",
                "practice_prerequisite",
                "practice_same_section",
                "verify_original",
                "finish",
            ],
            "requirements": [
                "不要生成新题；需要练习时只能调用固定题库中的真实题目",
                "先定位用户具体卡点，不要一开始倾倒完整答案",
                "前置知识明显薄弱时优先 practice_prerequisite",
                "用户明确要求出题、测试或练习时，必须选择 practice_prerequisite 或 practice_same_section",
                "没有合适的薄弱前置知识，或用户要求检查当前章节时，选择 practice_same_section",
                "例如‘给我出个题’、‘考考我’、‘再来一道’属于练习请求；‘题目这里为什么这样做’属于解释请求",
                "用户已经理解或补充题验证通过时可以 verify_original",
                "最多补充三道题；finish 只表示诊断可以结束",
                "reply 是给用户看的简短回复，不输出隐藏思维过程",
                "使用简体中文，控制在 350 字以内",
            ],
            "output_schema": {
                "reply": "给用户看的回复",
                "next_action": (
                    "ask_clarification|explain|practice_prerequisite|"
                    "practice_same_section|"
                    "verify_original|finish"
                ),
                "target_knowledge_id": "要补充的前置知识 id，没有则为 null",
                "gap": "当前判断的主要漏洞",
            },
        }
        data = self._json_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 FlowStudy 的诊断 Agent 噜噜。"
                        "你要通过题目、知识标签、掌握度和用户对话，"
                        "选择下一步最有帮助的学习动作。"
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.15,
            max_tokens=700,
            json_mode=False,
        )
        allowed = {
            "ask_clarification",
            "explain",
            "practice_prerequisite",
            "practice_same_section",
            "verify_original",
            "finish",
        }
        action = str(data.get("next_action", "ask_clarification"))
        if action not in allowed:
            action = "ask_clarification"
        return {
            "reply": self._clean_protocol_text(
                str(data.get("reply", "")),
                "你具体卡在哪一步？可以说说你的思路。",
            ),
            "next_action": action,
            "target_knowledge_id": data.get("target_knowledge_id"),
            "gap": str(data.get("gap", "需要继续确认具体卡点。")),
        }

    @staticmethod
    def native_diagnosis_tools() -> list[dict[str, Any]]:
        """OpenAI-compatible tool schemas for the optional native protocol."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_prerequisite_questions",
                    "description": "从固定题库检索指定前置知识的未做题。不要生成新题。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_knowledge_id": {"type": "string"},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 5},
                        },
                        "required": ["target_knowledge_id"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_same_section_questions",
                    "description": "从固定题库检索当前章节的未做题。不要生成新题。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "section_id": {"type": "string"},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 5},
                        },
                        "required": ["section_id"],
                        "additionalProperties": False,
                    },
                },
            },
        ]

    def diagnose_question_turn_native(
        self,
        *,
        question: dict[str, Any],
        original_user_answer: str,
        user_message: str,
        knowledge_tags: list[dict[str, Any]],
        section_mastery: dict[str, Any],
        weak_prerequisites: list[dict[str, Any]],
        prerequisite_mastery: list[dict[str, Any]],
        dialogue: list[dict[str, str]],
        support_results: list[dict[str, Any]],
        memory_context: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return a native tool call for the opt-in Function Calling path.

        This method deliberately exposes only safe retrieval tools. The
        application still validates arguments and owns all state changes.
        """
        payload = {
            "question": {
                "section_title": question.get("section_title", ""),
                "question_text": str(question.get("question_text", ""))[:1800],
            },
            "original_user_answer": original_user_answer,
            "user_message": user_message,
            "knowledge_tags": knowledge_tags,
            "section_mastery": section_mastery,
            "weak_prerequisites": weak_prerequisites,
            "prerequisite_mastery": prerequisite_mastery,
            "support_results": support_results[-3:],
            "learning_memories": [
                {"type": item.get("memory_type"), "content": item.get("content")}
                for item in (memory_context or [])[:12]
            ],
        }
        try:
            response = self._require_client().chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是 FlowStudy 的学习诊断 Agent。根据题目和学习证据决定下一步。"
                            "需要练题时必须调用一个固定题库工具；不要生成题目。"
                            "如果只是解释或追问，直接回复简短中文。"
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                tools=self.native_diagnosis_tools(),
                tool_choice="auto",
                temperature=0.15,
                max_tokens=700,
            )
            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None) or []
            if tool_calls:
                call = tool_calls[0]
                function = call.function
                name = str(function.name)
                try:
                    arguments = json.loads(function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    raise AIServiceError("噜噜导师返回的工具参数格式不完整，请稍后重试。") from exc
                if name == "search_prerequisite_questions":
                    return {
                        "reply": "我根据当前掌握情况先从前置知识题库里抽一道题。",
                        "next_action": "practice_prerequisite",
                        "target_knowledge_id": arguments.get("target_knowledge_id"),
                        "tool_name": name,
                        "tool_arguments": arguments,
                        "tool_call_id": str(getattr(call, "id", "native-call-1")),
                        "gap": "原生工具调用选择前置知识题",
                    }
                if name == "search_same_section_questions":
                    return {
                        "reply": "我先从当前章节的固定题库里抽一道题来检测。",
                        "next_action": "practice_same_section",
                        "target_knowledge_id": None,
                        "tool_name": name,
                        "tool_arguments": arguments,
                        "tool_call_id": str(getattr(call, "id", "native-call-1")),
                        "gap": "原生工具调用选择同章节题",
                    }
                raise AIServiceError(f"模型请求了未允许的工具：{name}")
            return {
                "reply": self._clean_protocol_text(
                    getattr(message, "content", None) or "",
                    "你具体卡在哪一步？",
                ),
                "next_action": "ask_clarification",
                "target_knowledge_id": None,
                "gap": "原生工具调用路径选择继续对话",
            }
        except AIServiceError:
            raise
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            raise AIServiceError(f"OpenRouter 原生工具调用失败：{exc}") from exc

    def complete_native_tool_call(
        self,
        *,
        user_message: str,
        tool_call_id: str,
        tool_name: str,
        tool_arguments: dict[str, Any],
        tool_result: Any,
    ) -> str:
        """Send a native tool result back and request the learner-facing reply."""
        try:
            response = self._require_client().chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是 FlowStudy 的学习 Agent。根据工具结果给出简短、准确的中文回复，不要生成新题。",
                    },
                    {"role": "user", "content": user_message},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tool_call_id,
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(tool_arguments, ensure_ascii=False),
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": json.dumps(tool_result, ensure_ascii=False, default=str)[:4000],
                    },
                ],
                tools=self.native_diagnosis_tools(),
                tool_choice="none",
                temperature=0.15,
                max_tokens=350,
            )
            return self._clean_protocol_text(
                response.choices[0].message.content or "",
                "我已经根据固定题库的查询结果安排好下一步了。",
            )
        except AIServiceError:
            raise
        except Exception as exc:
            raise AIServiceError(f"OpenRouter 工具结果回传失败：{exc}") from exc

    def diagnose_question_opening(
        self,
        *,
        question: dict[str, Any],
        original_user_answer: str,
        knowledge_tags: list[dict[str, Any]],
        prerequisite_mastery: list[dict[str, Any]],
        weak_prerequisites: list[dict[str, Any]],
    ) -> str:
        """Create the first learner-facing message from inspected evidence."""
        payload = {
            "question": {
                "section_title": question.get("section_title", ""),
                "question_text": str(question.get("question_text", ""))[:1800],
            },
            "original_user_answer": original_user_answer,
            "knowledge_tags": [
                {
                    "title": item.get("title"),
                    "relation": item.get("relation"),
                }
                for item in knowledge_tags
            ],
            "prerequisite_mastery": [
                {
                    "title": item.get("title"),
                    "mastery": item.get("mastery", {}),
                }
                for item in prerequisite_mastery
            ],
            "weak_prerequisites": [
                {
                    "title": item.get("title"),
                    "mastery": item.get("mastery", {}),
                }
                for item in weak_prerequisites
            ],
            "requirements": [
                "这是错因诊断对话的第一句话，必须先引用已经分析出的直接考点或前置知识",
                "如果存在薄弱前置知识，要指出它的答题次数和正确率，并说明为什么先关注它",
                "不要直接给出完整答案，也不要假装已经确定用户的真实错误原因",
                "最后只提出一个具体、容易回答的引导问题",
                "使用自然的简体中文，控制在 180 字以内，不提工具、Agent、提示词或隐藏思考",
            ],
        }
        return self._text_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 FlowStudy 的噜噜导师。"
                        "你已经完成了对题目标签和前置知识掌握度的观察，"
                        "现在要用证据充分的方式开启错因诊断对话。"
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.2,
            max_tokens=450,
        )

    def generate_question_dialogue_summary(
        self,
        *,
        section_title: str,
        question_text: str,
        answer_text: str = "",
        dialogue: list[dict[str, str]],
    ) -> dict[str, str]:
        payload = {
            "section": section_title,
            "question": question_text,
            "reference_answer": answer_text,
            "dialogue": dialogue[-20:],
            "requirements": [
                "只总结这道题的真实对话，不复述整份标准答案",
                "准确指出用户最初卡住的概念或推理步骤",
                "已理解内容必须能从对话中得到支持，不得虚构",
                "提炼一个可迁移到同类题的方法",
                "给出一句具体的下次提醒",
                "使用简体中文，内容具体、克制",
            ],
            "output_schema": {
                "stuck_point": "用户真正卡住的地方",
                "understood": "通过对话已经弄明白的内容",
                "method": "以后可以复用的方法",
                "next_reminder": "下次遇到同类题时的提醒",
            },
        }
        data = self._json_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 FlowStudy 的考研数学导师噜噜。"
                        "请根据一道题的辅导对话生成准确、有复习价值的学习总结。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            temperature=0.1,
        )
        stuck_point = str(data.get("stuck_point", "需要继续梳理解题入口。"))
        understood = str(data.get("understood", "已经完成了针对这道题的讨论。"))
        method = str(data.get("method", "先识别条件，再选择对应方法。"))
        next_reminder = str(data.get("next_reminder", "先说明每一步的依据。"))
        content = (
            "## 这道题的对话总结\n\n"
            f"**真正卡住的地方**\n{stuck_point}\n\n"
            f"**这次已经弄明白**\n{understood}\n\n"
            f"**可以复用的方法**\n{method}\n\n"
            f"**下次提醒**\n{next_reminder}"
        )
        return {
            "content": content,
            "mastered": understood,
            "mistakes": stuck_point,
            "insight": method,
            "next_suggestion": next_reminder,
            "review_focus": section_title,
            "rating": "",
        }

    def start_session(
        self,
        context: dict[str, Any],
        recent_dialogue: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        question = self.ask_question(context, 1, recent_dialogue)
        reply = (
            "## 开始本次航行\n\n"
            f"**目标：** {context['breadcrumb']}\n\n"
            "**本次挑战：** 5 道考研难度题\n\n"
            "完成后自动评级。\n\n"
            f"### 第 1 题\n\n{self.format_question(question)}"
        )
        return {"reply": reply, "question": question}

    def ask_question(
        self,
        context: dict[str, Any],
        question_number: int,
        recent_dialogue: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        payload = {
            **self._context_payload(context, recent_dialogue),
            "question_number": question_number,
            "total_questions": SESSION_QUESTION_COUNT,
            "requirements": [
                "只生成一道严格属于当前知识点的考研难度题",
                "优先考查理解、条件识别和方法选择，不出机械送分题",
                "若无法确认真题出处，source_type 必须为考研真题风格",
                "不要在题干中泄露答案",
            ],
            "output_schema": {
                "question": {
                    "type": "single|multiple|boolean",
                    "source_type": "考研真题|考研真题风格",
                    "source_note": "仅真题填写年份与题型，否则留空",
                    "question": "题干",
                    "options": ["选项A", "选项B", "选项C", "选项D"],
                    "answer": [0],
                    "explanation": "简洁严谨的答案依据",
                }
            },
        }
        data = self._json_completion(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ]
        )
        return self._normalize_question(
            data.get("question"),
            context["concept"],
            question_number,
        )

    def evaluate_answer(
        self,
        context: dict[str, Any],
        question: dict[str, Any],
        user_answer: str,
        question_number: int,
        recent_dialogue: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        is_last = question_number >= SESSION_QUESTION_COUNT
        payload = {
            **self._context_payload(context, recent_dialogue),
            "question_number": question_number,
            "total_questions": SESSION_QUESTION_COUNT,
            "question": question,
            "user_answer": user_answer,
            "is_last_question": is_last,
            "requirements": [
                "依据题目中保存的标准答案和解析判断，不迁就用户",
                "错误时明确 mistake_type，并用一个短追问帮助用户发现漏洞",
                "讲解控制在四句话内",
                "第5题只反馈，不再生成下一题",
            ],
            "output_schema": {
                "assessment": "correct|partial|incorrect",
                "is_correct": True,
                "mistake_type": "无|概念混淆|条件遗漏|公式误用|计算错误|审题错误|推理不完整",
                "feedback": "针对回答的简短反馈、追问与必要讲解",
                "next_question": (
                    None
                    if is_last
                    else {
                        "type": "single|multiple|boolean",
                        "source_type": "考研真题|考研真题风格",
                        "source_note": "",
                        "question": "下一题题干",
                        "options": ["A", "B", "C", "D"],
                        "answer": [0],
                        "explanation": "答案依据",
                    }
                ),
            },
        }
        data = self._json_completion(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ]
        )
        assessment = str(data.get("assessment", "incorrect"))
        if assessment not in {"correct", "partial", "incorrect"}:
            assessment = "incorrect"
        result: dict[str, Any] = {
            "assessment": assessment,
            "is_correct": assessment == "correct",
            "mistake_type": str(data.get("mistake_type", "推理不完整")),
            "feedback": str(data.get("feedback", "请重新检查条件与推理过程。")),
            "complete": is_last,
            "question": None,
        }
        if not is_last:
            result["question"] = self._normalize_question(
                data.get("next_question"),
                context["concept"],
                question_number + 1,
            )
        return result

    def generate_summary(
        self,
        context: dict[str, Any],
        attempts: list[dict[str, Any]],
        recent_dialogue: list[dict[str, str]] | None = None,
    ) -> dict[str, str]:
        correct_count = sum(bool(item.get("is_correct")) for item in attempts)
        rating = self.rating_for_score(correct_count)
        payload = {
            **self._context_payload(context, recent_dialogue),
            "correct_count": correct_count,
            "total_questions": SESSION_QUESTION_COUNT,
            "fixed_rating": rating,
            "attempts": attempts[-SESSION_QUESTION_COUNT:],
            "requirements": [
                "评级必须使用 fixed_rating，不得自行更改",
                "最大漏洞必须来自实际错题记录",
                "今日突破必须具体、克制，不虚构能力",
                "明确给出是否建议再次挑战及原因",
            ],
            "output_schema": {
                "rating": rating,
                "largest_gap": "最大漏洞",
                "breakthrough": "今日突破",
                "retry_recommended": "是|否",
                "retry_reason": "原因",
            },
        }
        data = self._json_completion(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            temperature=0.2,
        )
        largest_gap = str(data.get("largest_gap", "需要继续检查关键条件。"))
        breakthrough = str(data.get("breakthrough", "完成了五题完整挑战。"))
        retry = str(data.get("retry_recommended", "是"))
        retry_reason = str(data.get("retry_reason", "通过间隔复习确认稳定性。"))
        content = (
            f"## 本次航行总结\n\n"
            f"**航海评级**\n{rating}\n\n"
            f"**最大漏洞**\n{largest_gap}\n\n"
            f"**今日突破**\n{breakthrough}\n\n"
            f"**是否建议再次挑战**\n{retry}。{retry_reason}"
        )
        return {
            "rating": rating,
            "mastered": breakthrough,
            "mistakes": largest_gap,
            "insight": breakthrough,
            "next_suggestion": f"{retry}。{retry_reason}",
            "review_focus": context["concept"],
            "content": content,
        }

    def decide_repair_action(
        self,
        *,
        observation: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Choose one bounded repair action from real question candidates."""
        candidate_payload = [
            {
                "id": item["id"],
                "section_id": item["section_id"],
                "section_title": item["section_title"],
                "phase": item["phase"],
                "question_number": item["question_number"],
                "question_text": str(item.get("question_text", ""))[:700],
            }
            for item in candidates
        ]
        payload = {
            "observation": observation,
            "candidate_questions": candidate_payload,
            "allowed_actions": [
                "practice_same_section",
                "practice_prerequisite",
                "verify_original",
                "finish",
            ],
            "requirements": [
                "只能从 candidate_questions 中选择 question_id",
                "不能生成新题，不能修改题库答案",
                "补课最多三道题；达到上限必须 verify_original 或 finish",
                "答错后优先巩固当前章节或基础阶段，答对后优先回到原题验证",
                "用一句简短中文说明给用户，不输出隐藏思维过程",
            ],
            "output_schema": {
                "action": "practice_same_section|practice_prerequisite|verify_original|finish",
                "question_id": "候选题 id；不需要题目时为 null",
                "gap": "当前最可能的漏洞",
                "user_message": "给用户看的简短说明",
            },
        }
        data = self._json_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 FlowStudy 的学习诊断 Agent。"
                        "你通过有限的工具观察结果安排补课，不直接生成题目。"
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.1,
                    max_tokens=1200,
        )
        action = str(data.get("action", "verify_original"))
        allowed = {
            "practice_same_section",
            "practice_prerequisite",
            "verify_original",
            "finish",
        }
        if action not in allowed:
            action = "verify_original"
        question_id = data.get("question_id")
        candidate_ids = {item["id"] for item in candidates}
        if question_id not in candidate_ids:
            question_id = None
        if action in {"practice_same_section", "practice_prerequisite"} and not question_id:
            action = "verify_original"
        return {
            "action": action,
            "question_id": question_id,
            "gap": str(data.get("gap", "需要进一步确认当前知识点。")),
            "user_message": str(
                data.get("user_message", "先做一道相关题，再回到原题验证。")
            ),
        }

    def classify_question_batch(
        self,
        *,
        questions: list[dict[str, Any]],
        candidate_nodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Classify fixed-bank questions using only curated node candidates."""
        node_payload = [
            {
                "id": node["id"],
                "title": node["title"],
                "allowed_relations": node.get("allowed_relations", ["direct"]),
                "hints": node.get("hints", []),
            }
            for node in candidate_nodes
        ]
        question_payload = [
            {
                "id": question["id"],
                "section_title": question["section_title"],
                "subject": question["subject"],
                "phase": question["phase"],
                "question_text": str(question.get("question_text", ""))[:1200],
            }
            for question in questions
        ]
        payload = {
            "candidate_nodes": node_payload,
            "questions": question_payload,
            "requirements": [
                "每道题最多选择 3 个 direct 知识点和 3 个 prerequisite 知识点",
                "只能使用 candidate_nodes 中存在的 id",
                "direct 表示题目直接考查，prerequisite 表示解题需要的前置知识",
                "OCR 不清楚或题目为综合题时，可以返回空标签",
                "不要根据题号猜知识点，不要创造候选列表之外的 id",
            ],
            "output_schema": {
                "items": [
                    {
                        "question_id": "题目 id",
                        "direct_knowledge_ids": ["node id"],
                        "prerequisite_knowledge_ids": ["node id"],
                        "confidence": 0.0,
                        "reason": "不超过 30 字的分类依据",
                    }
                ]
            },
        }
        data = self._json_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是考研数学题目知识点标注器。"
                        "你只负责从给定目录中做保守分类，不解题，不补写题目。"
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.0,
            max_tokens=1800,
        )
        allowed_ids = {str(node["id"]) for node in candidate_nodes}
        question_ids = {str(question["id"]) for question in questions}
        normalized: list[dict[str, Any]] = []
        raw_items = data if isinstance(data, list) else data.get("items", [])
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            question_id = str(item.get("question_id", ""))
            if question_id not in question_ids:
                continue
            direct_ids = [
                str(value)
                for value in item.get("direct_knowledge_ids", [])
                if str(value) in allowed_ids
            ][:3]
            prerequisite_ids = [
                str(value)
                for value in item.get("prerequisite_knowledge_ids", [])
                if str(value) in allowed_ids
            ][:3]
            tags = [
                {
                    "knowledge_id": node_id,
                    "relation": "direct",
                    "confidence": item.get("confidence", 0.0),
                    "source": "ai_classifier",
                }
                for node_id in direct_ids
            ]
            tags.extend(
                {
                    "knowledge_id": node_id,
                    "relation": "prerequisite",
                    "confidence": item.get("confidence", 0.0),
                    "source": "ai_classifier",
                }
                for node_id in prerequisite_ids
                if node_id not in direct_ids
            )
            normalized.append(
                {
                    "question_id": question_id,
                    "tags": tags,
                    "confidence": min(
                        1.0, max(0.0, float(item.get("confidence", 0.0)))
                    ),
                    "reason": str(item.get("reason", ""))[:120],
                }
            )
        return normalized

    def generate_repair_report(self, facts: dict[str, Any]) -> dict[str, str]:
        """Turn verified repair facts into a concise learner-facing report."""
        payload = {
            "facts": facts,
            "requirements": [
                "只依据 facts 总结，不虚构用户能力",
                "指出原题漏洞、补过的知识点和是否修复",
                "给出一条下一次复习建议",
                "使用简体中文，控制在 400 字以内",
            ],
            "output_schema": {
                "title": "本次知识补全报告",
                "content": "报告正文",
                "next_suggestion": "下一次建议",
            },
        }
        data = self._json_completion(
            [
                {
                    "role": "system",
                    "content": "你是 FlowStudy 的学习总结助手，只能总结已经发生的补课事实。",
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.2,
            max_tokens=700,
        )
        title = str(data.get("title", "本次知识补全报告"))
        content = str(data.get("content", "本次补课已完成。"))
        next_suggestion = str(data.get("next_suggestion", "下次优先复习本题相关章节。"))
        return {
            "title": title,
            "content": content,
            "next_suggestion": next_suggestion,
        }

    @staticmethod
    def rating_for_score(correct_count: int) -> str:
        return {
            5: "⭐ 传奇发现者",
            4: "🌊 深海探索者",
            3: "⛵ 熟练航海家",
            2: "🌿 见习探索者",
        }.get(correct_count, "🌱 萌芽航海员")

    @staticmethod
    def format_question(question: dict[str, Any]) -> str:
        options = "\n".join(
            f"{chr(65 + index)}. {option}"
            for index, option in enumerate(question.get("options", []))
        )
        source = question.get("source_type", "考研真题风格")
        note = question.get("source_note")
        source_line = f"*{source}{f' · {note}' if note else ''}*"
        return f"{source_line}\n\n{question['question']}\n\n{options}".strip()
