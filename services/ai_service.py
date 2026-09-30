from __future__ import annotations

import json
import os
from typing import Any
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
    ) -> dict[str, Any]:
        try:
            response = self._require_client().chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or ""
            return json.loads(
                content.strip().removeprefix("```json").removesuffix("```").strip()
            )
        except AIServiceError:
            raise
        except (json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
            raise AIServiceError("噜噜导师返回的数据格式不完整，请稍后重试。") from exc
        except Exception as exc:
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
5. 使用简体中文和 Markdown，尽量控制在 500 字以内；
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
                max_tokens=800,
            )
            return (response.choices[0].message.content or "").strip()
        except AIServiceError:
            raise
        except Exception as exc:
            raise AIServiceError(f"OpenRouter 调用失败：{exc}") from exc

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
            max_tokens=500,
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
