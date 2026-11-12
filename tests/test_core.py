from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import flowstudy.database as database
import flowstudy.chat_agent as chat_agent
import flowstudy.views as views
from services.ai_service import AITutor
from flowstudy.views import (
    _chat_markdown,
    _format_elapsed,
    _markdown_math,
    _plain_math,
)
from flowstudy.content import (
    concept_for_question,
    get_concept,
    get_concepts,
    get_question,
    get_topic_tree,
    get_topics,
)


class ContentTests(unittest.TestCase):
    def test_topic_tree_and_questions_are_valid(self) -> None:
        topics = get_topics()
        self.assertEqual(len(topics), 11)
        self.assertEqual(
            [topic["topic"] for topic in topics[:3]],
            ["随机事件", "概率定义", "古典概率"],
        )
        for topic in topics:
            diagnostics = [
                question
                for question in topic["questions"]
                if question["phase"] == "diagnostic"
            ]
            self.assertEqual(len(diagnostics), 3)
        self.assertIsNotNone(get_question("d1q1"))

        tree = get_topic_tree()
        self.assertEqual(len(tree), 7)
        self.assertEqual(tree[0]["title"], "随机事件与概率")
        self.assertEqual(tree[6]["title"], "参数估计")
        self.assertEqual(
            tree[0]["high_frequency_points"][2],
            "条件概率、全概率和贝叶斯公式",
        )
        self.assertEqual(
            get_concept("chapter-7")["breadcrumb"],
            "参数估计",
        )
        self.assertEqual(len(get_concepts()), 7)

    def test_quiz_option_formatting_removes_raw_latex_for_widgets(self) -> None:
        option = r"$P(A\mid B)=P(A)$恒成立"
        self.assertEqual(_plain_math(option), "P(A | B)=P(A)恒成立")
        self.assertEqual(
            _markdown_math(option),
            r"$P(A\mid B)=P(A)$ 恒成立",
        )

    def test_chat_markdown_converts_latex_delimiters_for_rendering(self) -> None:
        content = r"参数为 \(t\in[0,\pi]\)。\n\[ds=\sqrt{dx^2+dy^2}\]"
        rendered = _chat_markdown(content)
        self.assertIn(r"$t\in[0,\pi]$", rendered)
        self.assertIn("$$\nds=", rendered)
        self.assertNotIn(r"\(", rendered)
        self.assertNotIn(r"\[", rendered)

    def test_elapsed_time_is_readable_during_chat_processing(self) -> None:
        self.assertEqual(_format_elapsed(3.9), "3秒")
        self.assertEqual(_format_elapsed(65), "1分05秒")

    def test_route_helpers_follow_question_bank_order(self) -> None:
        sections = [
            {"id": "foundation-calculus-01", "attempts": 5, "correct_attempts": 3},
            {"id": "foundation-calculus-02", "attempts": 0, "correct_attempts": 0},
        ]
        self.assertEqual(
            views._first_unexplored_section_id(sections),
            "foundation-calculus-02",
        )

    def test_direct_knowledge_question_does_not_become_weakness_analysis(self) -> None:
        self.assertTrue(
            chat_agent._is_direct_learning_question("分块矩阵的变化有哪些")
        )
        self.assertFalse(
            chat_agent._is_direct_learning_question("最近学习情况怎么样")
        )
        self.assertFalse(
            chat_agent._is_direct_learning_question("帮我找找薄弱点")
        )

    def test_chat_can_practice_from_a_new_session(self) -> None:
        state = {"messages": [], "current_question": None}
        question = {
            "id": "chat-q1",
            "section_title": "测试章节",
            "question_number": 1,
            "question_text": "测试题",
            "options": ["A", "B"],
            "question_images": ["assets/test-question.png"],
        }
        def tool(name: str, arguments: dict[str, object]) -> object:
            if name == "get_weak_concepts":
                return []
            return question

        with (
            patch.object(chat_agent, "get_agent_memories", return_value=[]),
            patch.object(
                chat_agent,
                "AITutor",
                return_value=SimpleNamespace(enabled=False),
            ),
            patch.object(chat_agent, "call_agent_tool", side_effect=tool),
        ):
            stages = []
            result = chat_agent.chat_turn(
                state,
                "给我出一道题",
                progress_callback=stages.append,
            )

        self.assertEqual(result["current_question"]["id"], "chat-q1")
        self.assertIn("请直接回复你的选项", result["messages"][-1]["content"])
        self.assertIn("当前没有可用的薄弱点题目，正在从固定题库选择未做题", stages)
        self.assertEqual(
            result["messages"][-1]["question"]["question_images"],
            ["assets/test-question.png"],
        )

    def test_generic_practice_checks_weaknesses_before_fixed_bank_question(self) -> None:
        state = {"messages": [], "current_question": None}
        weak = [
            {
                "concept_id": "kp:calculus:double-integral",
                "concept": "二重积分",
                "mastery": 0.25,
            }
        ]
        question = {
            "id": "double-integral-q1",
            "section_title": "二重积分基础",
            "question_number": 1,
            "question_text": "计算二重积分。",
            "options": [],
            "question_images": [],
        }
        calls: list[tuple[str, dict[str, object]]] = []

        def tool(name: str, arguments: dict[str, object]) -> object:
            calls.append((name, arguments))
            if name == "get_weak_concepts":
                return weak
            if name == "choose_question_for_knowledge":
                return question
            raise AssertionError(f"不应调用工具：{name}")

        with (
            patch.object(chat_agent, "AITutor", return_value=SimpleNamespace(enabled=False)),
            patch.object(chat_agent, "call_agent_tool", side_effect=tool),
        ):
            result = chat_agent.chat_turn(state, "能帮我出道题检验一下吗")

        self.assertEqual(result["current_question"]["id"], "double-integral-q1")
        self.assertEqual(
            [name for name, _ in calls],
            ["get_weak_concepts", "choose_question_for_knowledge"],
        )
        self.assertEqual(
            calls[1][1]["knowledge_id"], "kp:calculus:double-integral"
        )
        self.assertEqual(result["tool_trace"][0]["tool"], "get_weak_concepts")

    def test_natural_gap_filling_request_retrieves_a_fixed_bank_question(self) -> None:
        state = {"messages": [], "current_question": None}
        question = {
            "id": "gap-fill-q1",
            "section_title": "二重积分基础",
            "question_number": 1,
            "question_text": "计算二重积分。",
            "options": [],
            "question_images": [],
        }

        def tool(name: str, arguments: dict[str, object]) -> object:
            if name == "get_weak_concepts":
                return []
            if name == "choose_daily_question":
                return question
            raise AssertionError(f"不应调用工具：{name}")

        with (
            patch.object(chat_agent, "AITutor", return_value=SimpleNamespace(enabled=False)),
            patch.object(chat_agent, "call_agent_tool", side_effect=tool),
        ):
            result = chat_agent.chat_turn(state, "帮我查漏补缺")

        self.assertEqual(result["current_question"]["id"], "gap-fill-q1")
        self.assertIn("计算二重积分", result["messages"][-1]["content"])

    def test_named_follow_up_inherits_an_unfinished_practice_request(self) -> None:
        state = {
            "messages": [
                {"role": "assistant", "content": "你想练哪一章？"},
                {"role": "user", "content": "出道题"},
                {
                    "role": "assistant",
                    "content": "你可以继续告诉我想解决的学习问题。",
                },
            ],
            "current_question": None,
        }
        question = {
            "id": "double-integral-follow-up-q1",
            "section_title": "二重积分",
            "question_number": 1,
            "question_text": "计算二重积分。",
            "options": [],
            "question_images": [],
        }
        self.assertEqual(
            chat_agent._pending_practice_intent(state),
            "practice_needs_topic",
        )

        with (
            patch.object(chat_agent, "AITutor", return_value=SimpleNamespace(enabled=False)),
            patch.object(chat_agent, "call_agent_tool", return_value=question) as tool,
        ):
            result = chat_agent.chat_turn(state, "二重积分")

        self.assertEqual(result["last_action"], "practice")
        self.assertEqual(
            result["current_question"]["id"],
            "double-integral-follow-up-q1",
        )
        tool.assert_called_once_with(
            "choose_question_for_knowledge",
            {
                "knowledge_id": "kp:calculus:double-integral",
                "exclude_ids": [""],
            },
        )

    def test_chat_prefers_fixed_question_explanation_for_a_follow_up(self) -> None:
        question = {
            "id": "fixed-explanation-q1",
            "section_title": "二重积分",
            "question_number": 1,
            "question_text": "计算题",
            "answer_text": "固定解析：先确定积分区域，再选择积分次序。",
            "answer_images": ["data/question_bank/example/answers/q001.webp"],
        }
        state = {
            "messages": [
                {"role": "assistant", "content": "如果需要进一步的解题步骤，请告诉我。"},
                {"role": "user", "content": "是5吗"},
                {"role": "assistant", "content": "答案需要结合题目条件判断。"},
            ],
            "current_question": question,
        }

        with patch.object(
            chat_agent, "AITutor", return_value=SimpleNamespace(enabled=False)
        ):
            result = chat_agent.chat_turn(state, "需要")

        self.assertEqual(result["last_action"], "explain_fixed_question")
        self.assertIn("固定解析：先确定积分区域", result["messages"][-1]["content"])
        self.assertEqual(
            result["messages"][-1]["answer_images"],
            ["data/question_bank/example/answers/q001.webp"],
        )
        self.assertEqual(result["current_question"]["id"], "fixed-explanation-q1")

    def test_chat_does_not_fetch_question_for_ambiguous_confusion(self) -> None:
        state = {"messages": [], "current_question": None}
        tutor = SimpleNamespace(
            enabled=True,
            chat_agent_turn=lambda **_: {
                "reply": "你可以告诉我想聊的内容。",
                "next_action": "answer",
                "memory": "",
            },
        )
        with (
            patch.object(chat_agent, "get_agent_memories", return_value=[]),
            patch.object(chat_agent, "get_weak_concepts", return_value=[]),
            patch.object(chat_agent, "AITutor", return_value=tutor),
            patch.object(chat_agent, "call_agent_tool") as choose_question,
        ):
            result = chat_agent.chat_turn(state, "我也不知道哪里不懂")

        choose_question.assert_not_called()
        self.assertEqual(result["last_action"], "answer")

    def test_chat_analyzes_weaknesses_before_waiting_for_a_natural_language_choice(self) -> None:
        state = {"messages": [], "current_question": None}
        weak = [
            {
                "concept": "条件概率与贝叶斯公式",
                "mastery": 0.35,
                "recent_attempts": 4,
                "recent_accuracy": 0.25,
                "wrong_count": 2,
            }
        ]
        def tool(name: str, arguments: dict[str, object]) -> object:
            self.assertEqual(name, "get_weak_concepts")
            return weak

        with (
            patch.object(chat_agent, "call_agent_tool", side_effect=tool) as choose_question,
            patch.object(
                chat_agent,
                "AITutor",
                return_value=SimpleNamespace(
                    enabled=True,
                    chat_agent_turn=lambda **_: {
                        "reply": "我根据答题记录先分析这一个薄弱点。",
                        "next_action": "review_weakest",
                        "memory": "",
                        "target_knowledge_id": None,
                    },
                ),
            ) as tutor,
        ):
            result = chat_agent.chat_turn(state, "分析一下我的薄弱点")

        self.assertEqual(
            [call.args[0] for call in choose_question.call_args_list],
            ["get_weak_concepts"],
        )
        tutor.assert_called_once()
        self.assertEqual(result["last_action"], "analyze_weakness")
        self.assertIn("根据答题记录", result["messages"][-1]["content"])

    def test_chat_recognizes_a_request_to_find_my_weaknesses(self) -> None:
        state = {"messages": [], "current_question": None}
        weak = [
            {
                "concept": "函数极限",
                "mastery": 0.4,
                "attempts": 5,
                "recent_attempts": 2,
                "recent_accuracy": 0.0,
                "wrong_count": 2,
            }
        ]

        with (
            patch.object(chat_agent, "AITutor", return_value=SimpleNamespace(enabled=False)),
            patch.object(
                chat_agent,
                "call_agent_tool",
                return_value=weak,
            ) as tool,
        ):
            result = chat_agent.chat_turn(state, "你能帮我找找我的弱点吗")

        self.assertEqual(result["last_action"], "analyze_weakness")
        self.assertIn("函数极限", result["messages"][-1]["content"])
        tool.assert_called_once_with("get_weak_concepts", {"limit": 8})

    def test_chat_sends_off_topic_conversation_to_llm_without_learning_context(self) -> None:
        state = {"messages": [], "current_question": None}
        tutor = SimpleNamespace(
            enabled=True,
            chat_agent_turn=lambda **kwargs: {
                "reply": "听起来你只是想聊聊天，我在。",
                "next_action": "answer",
                "memory": "",
                "target_knowledge_id": None,
            },
        )
        with (
            patch.object(chat_agent, "get_weak_concepts") as weak,
            patch.object(chat_agent, "AITutor", return_value=tutor),
        ):
            stages: list[str] = []
            result = chat_agent.chat_turn(
                state,
                "最近看了部电影，心情还不错",
                progress_callback=stages.append,
            )

        weak.assert_not_called()
        self.assertIn("只是想聊聊天", result["messages"][-1]["content"])
        self.assertIn("正在结合最近对话理解你的问题", stages)
        self.assertIn("正在组织与你当前问题相关的回复", stages)

    def test_chat_passes_registered_tools_to_llm_router(self) -> None:
        state = {"messages": [], "current_question": None}
        captured: dict[str, object] = {}

        def route(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {
                "reply": "我先听你说说。",
                "next_action": "answer",
                "memory": "",
                "target_knowledge_id": None,
                "tool_name": None,
                "tool_arguments": {},
            }

        with patch.object(
            chat_agent,
            "AITutor",
            return_value=SimpleNamespace(enabled=True, chat_agent_turn=route),
        ):
            chat_agent.chat_turn(state, "最近看了部电影")

        tools = captured.get("available_tools")
        self.assertIsInstance(tools, list)
        names = {item["name"] for item in tools}  # type: ignore[index]
        self.assertIn("get_weak_concepts", names)
        self.assertIn("choose_question_for_knowledge", names)
        self.assertIn("choose_daily_question", names)

    def test_chat_recognizes_natural_weakness_question(self) -> None:
        state = {"messages": [], "current_question": None}
        weak = [{"concept": "函数极限", "mastery": 0.4, "attempts": 3}]
        with (
            patch.object(chat_agent, "AITutor", return_value=SimpleNamespace(enabled=False)),
            patch.object(chat_agent, "call_agent_tool", return_value=weak) as tool,
        ):
            result = chat_agent.chat_turn(state, "看看我哪里比较弱")

        self.assertEqual(result["last_action"], "analyze_weakness")
        tool.assert_called_once_with("get_weak_concepts", {"limit": 8})

    def test_chat_executes_llm_weakness_tool_request_on_contextual_follow_up(self) -> None:
        state = {
            "messages": [
                {"role": "user", "content": "我不知道我哪里掌握得不好"},
                {"role": "assistant", "content": "你可以说帮我分析。"},
            ],
            "current_question": None,
        }
        weak = [{"concept": "二重积分", "mastery": 0.3, "attempts": 4}]
        tutor = SimpleNamespace(
            enabled=True,
            chat_agent_turn=lambda **_: {
                "reply": "我来根据答题记录分析你的薄弱点。",
                "next_action": "review_weakest",
                "memory": "",
                "target_knowledge_id": None,
                "tool_name": "get_weak_concepts",
                "tool_arguments": {"limit": 8},
            },
        )
        with (
            patch.object(chat_agent, "AITutor", return_value=tutor),
            patch.object(chat_agent, "call_agent_tool", return_value=weak) as tool,
        ):
            result = chat_agent.chat_turn(state, "帮我分析")

        self.assertEqual(result["last_action"], "analyze_weakness")
        tool.assert_called_once_with("get_weak_concepts", {"limit": 8})

    def test_chat_uses_context_to_query_weaknesses_when_model_tool_field_is_missing(self) -> None:
        state = {
            "messages": [
                {"role": "user", "content": "我不知道我哪里掌握得不好"},
                {
                    "role": "assistant",
                    "content": "你想先分析薄弱点还是做一些诊断题呢？",
                },
            ],
            "current_question": None,
        }
        weak = [{"concept": "多元函数积分学", "mastery": 0.33, "attempts": 6}]
        tutor = SimpleNamespace(
            enabled=True,
            chat_agent_turn=lambda **_: {
                "reply": "我正在分析你的学习记录。",
                "next_action": "review_weakest",
                "memory": "",
                "target_knowledge_id": None,
            },
        )
        with (
            patch.object(chat_agent, "AITutor", return_value=tutor),
            patch.object(chat_agent, "call_agent_tool", return_value=weak) as tool,
        ):
            result = chat_agent.chat_turn(state, "帮我分析")

        self.assertEqual(result["last_action"], "analyze_weakness")
        tool.assert_called_once_with("get_weak_concepts", {"limit": 8})

    def test_chat_uses_llm_review_action_for_natural_learning_follow_up(self) -> None:
        state = {
            "messages": [
                {"role": "user", "content": "我也不知道哪里差"},
                {"role": "assistant", "content": "你可以选择答题记录。"},
            ],
            "current_question": None,
        }
        weak = [{"concept": "导数与微分的定义", "mastery": 0.62, "attempts": 8}]
        tutor = SimpleNamespace(
            enabled=True,
            chat_agent_turn=lambda **_: {
                "reply": "我先查看你的答题记录。",
                "next_action": "review_weakest",
                "memory": "",
                "target_knowledge_id": None,
            },
        )
        with (
            patch.object(chat_agent, "AITutor", return_value=tutor),
            patch.object(chat_agent, "call_agent_tool", return_value=weak) as tool,
        ):
            result = chat_agent.chat_turn(state, "答题记录")

        self.assertEqual(result["last_action"], "analyze_weakness")
        tool.assert_called_once_with("get_weak_concepts", {"limit": 8})

    def test_chat_preserves_a_self_reported_topic_for_follow_up_analysis(self) -> None:
        state = {"messages": [], "current_question": None}
        with patch.object(
            chat_agent,
            "AITutor",
            return_value=SimpleNamespace(enabled=False),
        ):
            reported = chat_agent.chat_turn(state, "微分方程学的一般")
        self.assertEqual(
            reported["self_reported_concepts"][0]["id"],
            "kp:calculus:differential-equation",
        )
        self.assertIn("微分方程", reported["messages"][-1]["content"])

        with (
            patch.object(chat_agent, "get_weak_concepts", return_value=[]),
            patch.object(
                chat_agent,
                "AITutor",
                return_value=SimpleNamespace(enabled=False),
            ),
        ):
            analyzed = chat_agent.chat_turn(reported, "分析一下我的薄弱点")

        self.assertIn("微分方程", analyzed["messages"][-1]["content"])
        self.assertIn("主观反馈", analyzed["messages"][-1]["content"])

    def test_chat_uses_the_knowledge_point_when_requesting_a_question(self) -> None:
        state = {"messages": [], "current_question": None}
        question = {
            "id": "differential-q1",
            "section_title": "微分方程及其应用",
            "question_number": 1,
            "question_text": "测试题",
            "options": ["A", "B"],
            "question_images": [],
        }
        with (
            patch.object(
                chat_agent,
                "AITutor",
                return_value=SimpleNamespace(enabled=False),
            ),
            patch.object(chat_agent, "call_agent_tool", return_value=question) as tool,
        ):
            result = chat_agent.chat_turn(state, "给我做一道微分方程的题")

        tool.assert_called_once_with(
            "choose_question_for_knowledge",
            {
                "knowledge_id": "kp:calculus:differential-equation",
                "exclude_ids": [""],
            },
        )
        self.assertEqual(result["current_question"]["id"], "differential-q1")

    def test_chat_treats_want_to_do_a_named_knowledge_point_as_practice(self) -> None:
        state = {"messages": [], "current_question": None}
        question = {
            "id": "derivative-definition-q1",
            "section_title": "导数与微分的定义",
            "question_number": 1,
            "question_text": "测试导数定义。",
            "options": ["A", "B"],
            "question_images": [],
        }
        with (
            patch.object(chat_agent, "AITutor", return_value=SimpleNamespace(enabled=False)),
            patch.object(chat_agent, "call_agent_tool", return_value=question) as tool,
        ):
            result = chat_agent.chat_turn(state, "我想做导数与微分的定义")

        self.assertEqual(result["last_action"], "practice")
        self.assertEqual(result["current_question"]["id"], "derivative-definition-q1")
        tool.assert_called_once_with(
            "choose_question_for_knowledge",
            {
                "knowledge_id": "kp:calculus:derivative-definition",
                "exclude_ids": [""],
            },
        )


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = database.DB_PATH
        database.DB_PATH = Path(self.temp_dir.name) / "test.db"
        database.init_db()

    def tearDown(self) -> None:
        database.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_attempt_creates_complete_wrong_question_and_can_resolve(self) -> None:
        question = get_topics()[0]["questions"][0]
        database.record_attempt(
            question, "random-events", [1], False, "diagnostic"
        )
        wrong = database.get_wrong_questions()
        self.assertEqual(len(wrong), 1)
        self.assertIn("options", wrong[0]["question_json"])
        self.assertEqual(wrong[0]["last_selected_answer"], "[1]")

        database.resolve_wrong_question(question["id"])
        self.assertEqual(database.get_wrong_questions(), [])
        self.assertEqual(len(database.get_wrong_questions(True)), 1)

        database.delete_wrong_question(question["id"])
        self.assertEqual(database.get_wrong_questions(True), [])

    def test_ai_tutor_question_can_be_saved_as_reef_record(self) -> None:
        concept = get_concept("chapter-1")
        question = {
            "id": "ai-tutor-test-1",
            "phase": "tutor",
            "type": "single",
            "knowledge_point": concept["concept"],
            "question": "若 A 包含于 B，哪项一定成立？",
            "options": ["A发生则B发生", "B发生则A发生"],
            "answer": [0],
            "explanation": "A 是 B 的子事件。",
            "concept_id": concept["id"],
            "last_user_answer": "我选第二项",
            "source": "ai_tutor",
        }
        database.record_attempt(
            question,
            concept["topic_id"],
            [],
            False,
            "tutor",
            update_mastery=False,
        )
        wrong = database.get_wrong_questions()
        self.assertEqual(len(wrong), 1)
        self.assertIn("我选第二项", wrong[0]["question_json"])
        self.assertIn("A 是 B 的子事件", wrong[0]["question_json"])

    def test_incorrect_tutor_turn_automatically_creates_reef_record(self) -> None:
        concept = get_concept("chapter-1")
        question = {
            "id": "ai-tutor-live-1",
            "phase": "tutor",
            "type": "single",
            "knowledge_point": concept["concept"],
            "question": "若 A 包含于 B，哪项一定成立？",
            "options": ["A发生则B发生", "B发生则A发生"],
            "answer": [0],
            "explanation": "A 是 B 的子事件。",
        }
        session_id = database.start_tutor_session(concept["id"])
        database.update_tutor_context(
            session_id,
            {
                "current_question": question,
                "asked_ids": [question["id"]],
                "assessments": [],
            },
        )
        session = database.get_tutor_session(session_id)
        with patch.object(
            views,
            "tutor_turn",
            return_value={
                "assessment": "incorrect",
                "is_correct": False,
                "mistake_type": "条件遗漏",
                "complete": False,
                "reply": "再想想包含关系。",
                "question": {**question, "id": "ai-tutor-live-2"},
            },
        ):
            views._process_tutor_answer(session, "我选第二项")

        wrong = database.get_wrong_questions()
        self.assertEqual(len(wrong), 1)
        self.assertEqual(wrong[0]["question_id"], "ai-tutor-live-1")
        self.assertIn("我选第二项", wrong[0]["question_json"])
        attempts = database.get_ai_tutor_attempts(session_id)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["mistake_type"], "条件遗漏")

    def test_activity_and_daily_stats(self) -> None:
        database.record_activity("random-events", 90)
        stats = database.get_stats()
        self.assertEqual(stats["today_seconds"], 90)
        self.assertEqual(stats["week_seconds"], 90)
        self.assertEqual(stats["total_seconds"], 90)
        self.assertEqual(len(database.get_daily_stats()), 1)

    def test_fixed_question_bank_selection_and_wrong_record(self) -> None:
        with database.connection() as conn:
            conn.execute(
                """
                INSERT INTO question_bank_sections(
                    id, batch, phase, subject, chapter_number, title,
                    question_page_start, question_page_end,
                    answer_page_start, answer_page_end, question_count
                ) VALUES ('section-1', 1, 'foundation', 'calculus', 1,
                          '函数极限', 1, 1, 1, 1, 1)
                """
            )
            conn.execute(
                """
                INSERT INTO question_bank(
                    id, section_id, question_number, question_type,
                    question_text, question_images_json, answer_text,
                    answer_choice, answer_images_json, auto_gradable,
                    confidence, review_status, source_question_pages
                ) VALUES ('bank-q1', 'section-1', 1, 'choice', '测试题',
                          '["q.webp"]', '(B)', 'B', '["a.webp"]',
                          1, .95, 'verified', '1')
                """
            )
        questions = database.choose_question_bank_questions("section-1")
        self.assertEqual(questions[0]["answer_choice"], "B")
        database.record_question_bank_attempt(questions[0], "A", False)
        self.assertEqual(database.get_wrong_questions()[0]["question_id"], "bank-q1")

    def test_question_bank_exposes_all_imported_subjects(self) -> None:
        with database.connection() as conn:
            for section_id, subject in (
                ("calculus-section", "calculus"),
                ("linear-section", "linear_algebra"),
                ("probability-section", "probability"),
            ):
                conn.execute(
                    """
                    INSERT INTO question_bank_sections(
                        id, batch, phase, subject, chapter_number, title,
                        question_page_start, question_page_end,
                        answer_page_start, answer_page_end, question_count
                    ) VALUES (?, 1, 'foundation', ?, 1, ?, 1, 1, 1, 1, 0)
                    """,
                    (section_id, subject, section_id),
                )

        sections = database.get_question_bank_sections()
        self.assertEqual(
            [section["id"] for section in sections],
            [
                "calculus-section",
                "linear-section",
                "probability-section",
            ],
        )
        self.assertTrue(
            all(section["source"] == "zhangyu1000" for section in sections)
        )

    def test_growth_overview_treats_unseen_concepts_as_seed(self) -> None:
        growth = database.get_growth_overview()
        self.assertEqual(growth["overall"], 0.0)
        self.assertEqual(
            growth["distribution"]["seed"],
            growth["concept_count"],
        )
        self.assertEqual(database.mastery_level(0.19)["name"], "萌芽")
        self.assertEqual(database.mastery_level(0.2)["name"], "成长")
        self.assertEqual(database.mastery_level(0.5)["name"], "熟练")
        self.assertEqual(database.mastery_level(0.8)["name"], "精通")

    def test_weakness_analysis_ignores_unseen_seeded_concepts(self) -> None:
        self.assertEqual(database.get_weak_concepts(), [])

    def test_topic_progress(self) -> None:
        database.save_topic_progress(
            "random-events", mastery=0.8, diagnostic_score=2 / 3, completed=True
        )
        row = database.get_topic_progress()["random-events"]
        self.assertAlmostEqual(row["mastery"], 0.8)
        self.assertEqual(row["completed"], 1)

    def test_concept_mastery_and_weakness_use_history(self) -> None:
        topic = get_topics()[3]
        question = topic["questions"][2]
        concept = concept_for_question(topic, question)
        before = database.get_concept_mastery()[concept["id"]]["mastery"]
        database.record_attempt(question, topic["id"], [2], False, "review")
        after = database.get_concept_mastery()[concept["id"]]["mastery"]
        self.assertLess(after, before)
        weak_ids = [item["concept_id"] for item in database.get_weak_concepts(5)]
        self.assertIn(concept["id"], weak_ids)

    def test_tutor_session_summary_and_favorite(self) -> None:
        concept = get_concepts()[0]
        session_id = database.start_tutor_session(concept["id"])
        database.update_tutor_context(
            session_id,
            {"current_question": {"id": "q1"}, "asked_ids": ["q1"]},
        )
        database.add_tutor_message(
            session_id, "assistant", "先问一个问题", concept["id"]
        )
        database.add_tutor_message(
            session_id, "user", "我的回答", concept["id"]
        )
        database.add_tutor_message(
            session_id,
            "assistant",
            "继续追问",
            concept["id"],
            "partial",
        )
        self.assertEqual(len(database.get_tutor_messages(session_id)), 3)
        self.assertIsNotNone(database.get_active_tutor_session())

        summary = {
            "content": "总结",
            "mastered": "掌握",
            "mistakes": "错误",
            "insight": "顿悟",
            "next_suggestion": "建议",
            "review_focus": concept["concept"],
        }
        summary_id = database.finish_tutor_session(session_id, summary)
        database.set_summary_favorite(summary_id, True)
        self.assertIsNone(database.get_active_tutor_session())
        self.assertEqual(len(database.get_summaries(favorites_only=True)), 1)

    def test_starting_selected_concept_replaces_old_active_session(self) -> None:
        first = database.start_tutor_session("chapter-1")
        second = database.start_tutor_session("chapter-4")
        self.assertNotEqual(first, second)
        self.assertEqual(
            database.get_tutor_session(first)["status"],
            "abandoned",
        )
        self.assertEqual(
            database.get_active_tutor_session()["focus_concept_id"],
            "chapter-4",
        )

    def test_ai_attempt_rating_and_summary_are_persisted(self) -> None:
        session_id = database.start_tutor_session("chapter-1")
        question = {
            "id": "openrouter-test",
            "question": "测试题",
            "options": ["A", "B"],
            "answer": [0],
            "explanation": "解析",
            "knowledge_point": "随机事件",
        }
        for index in range(5):
            database.record_ai_tutor_attempt(
                session_id,
                "chapter-1",
                "chapter-1",
                {**question, "id": f"openrouter-test-{index}"},
                "A",
                index < 4,
                "无" if index < 4 else "条件遗漏",
            )
        database.finalize_ai_tutor_attempts(
            session_id,
            "chapter-1",
            4,
            "🌊 深海探索者",
            "本次航行总结",
        )
        attempts = database.get_ai_tutor_attempts(session_id)
        self.assertEqual(len(attempts), 5)
        self.assertTrue(all(row["rating"] == "🌊 深海探索者" for row in attempts))
        session = database.get_tutor_session(session_id)
        self.assertEqual(session["correct_count"], 4)
        self.assertEqual(session["rating"], "🌊 深海探索者")


class _FakeCompletions:
    def __init__(self, payloads: list[str]) -> None:
        self.payloads = payloads
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.payloads.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class _FakeOpenAI:
    def __init__(self, payloads: list[str]) -> None:
        self.completions = _FakeCompletions(payloads)
        self.chat = SimpleNamespace(completions=self.completions)


class _FakeNativeOpenAI:
    def __init__(self, tool_name: str, arguments: dict) -> None:
        function = SimpleNamespace(
            name=tool_name,
            arguments=__import__("json").dumps(arguments),
        )
        message = SimpleNamespace(content=None, tool_calls=[SimpleNamespace(function=function)])
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=message)])
            )
        )


class AIServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = {
            "topic": "随机事件与概率",
            "concept": "乘法公式",
            "breadcrumb": "条件概率 > 乘法公式",
            "mastery": 0.3,
            "rank": "🌿 见习探索者",
            "weakness": "条件遗漏",
        }
        self.question_payload = """
        {
          "question": {
            "type": "single",
            "source_type": "考研真题风格",
            "source_note": "",
            "question": "设事件A、B满足条件，正确的是？",
            "options": ["选项1", "选项2", "选项3", "选项4"],
            "answer": [0],
            "explanation": "由乘法公式可知。"
          }
        }
        """

    def test_start_session_and_fifth_answer_stop_after_five_questions(self) -> None:
        evaluation = """
        {
          "assessment": "incorrect",
          "is_correct": false,
          "mistake_type": "公式误用",
          "feedback": "先检查条件概率中的条件事件。"
        }
        """
        fake = _FakeOpenAI([self.question_payload, evaluation])
        tutor = AITutor(api_key="test", client=fake)
        opening = tutor.start_session(self.context)
        self.assertIn("5 道考研难度题", opening["reply"])
        result = tutor.evaluate_answer(
            self.context,
            opening["question"],
            "B",
            5,
            [{"role": "user", "content": "B"}] * 12,
        )
        self.assertTrue(result["complete"])
        self.assertIsNone(result["question"])
        request_payload = fake.completions.calls[1]["messages"][1]["content"]
        self.assertEqual(len(__import__("json").loads(request_payload)["recent_dialogue"]), 10)

    def test_connection_uses_configured_client(self) -> None:
        tutor = AITutor(
            api_key="test",
            client=_FakeOpenAI(["OK"]),
        )
        self.assertTrue(tutor.test_connection())

    def test_question_explanation_keeps_recent_dialogue(self) -> None:
        fake = _FakeOpenAI(["先检查你提到的第二步。"])
        tutor = AITutor(api_key="test", client=fake)
        answer = tutor.explain_question(
            section_title="函数极限",
            question_text="求给定函数的极限。",
            answer_text="结果为 1。",
            user_question="为什么这里可以等价替换？",
            recent_dialogue=[
                {"role": "user", "content": "我不理解第二步。"},
                {"role": "assistant", "content": "先看替换条件。"},
            ],
        )
        self.assertIn("第二步", answer)
        messages = fake.completions.calls[0]["messages"]
        self.assertEqual(messages[-3]["content"], "我不理解第二步。")
        self.assertEqual(messages[-2]["content"], "先看替换条件。")
        self.assertEqual(messages[-1]["content"], "为什么这里可以等价替换？")

    def test_daily_diagnosis_turn_returns_agent_action(self) -> None:
        payload = """
        {
          "reply": "这道题需要先补一遍偏导数的基础。",
          "next_action": "practice_prerequisite",
          "target_knowledge_id": "kp:calculus:multivariable-derivative",
          "gap": "偏导数基础不稳"
        }
        """
        fake = _FakeOpenAI([payload])
        tutor = AITutor(api_key="test", client=fake)
        result = tutor.diagnose_question_turn(
            question={
                "section_title": "多元函数微分学",
                "question_text": "求函数在某点的极值。",
                "answer_text": "先求一阶偏导数。",
            },
            original_user_answer="我直接套了公式。",
            user_message="我不知道为什么要先求偏导。",
            knowledge_tags=[
                {
                    "id": "kp:calculus:multivariable-extreme",
                    "title": "多元函数极值与条件极值",
                    "relation": "direct",
                }
            ],
            section_mastery={"attempts": 2, "accuracy": 0.5},
            weak_prerequisites=[
                {
                    "id": "kp:calculus:multivariable-derivative",
                    "title": "多元函数微分学",
                    "mastery": {"attempts": 3, "accuracy": 0.33},
                }
            ],
            prerequisite_mastery=[
                {
                    "id": "kp:calculus:multivariable-derivative",
                    "title": "多元函数微分学",
                    "mastery": {"attempts": 3, "accuracy": 0.33},
                }
            ],
            dialogue=[],
            support_results=[],
        )
        self.assertEqual(result["next_action"], "practice_prerequisite")
        self.assertEqual(
            result["target_knowledge_id"],
            "kp:calculus:multivariable-derivative",
        )
        request = fake.completions.calls[0]["messages"][1]["content"]
        self.assertIn("practice_prerequisite", request)
        self.assertIn("practice_same_section", request)

    def test_daily_diagnosis_turn_can_choose_same_section_question(self) -> None:
        payload = """
        {
          "reply": "我从固定题库抽一道同章节题来检测一下。",
          "next_action": "practice_same_section",
          "target_knowledge_id": null,
          "gap": "需要检测当前章节掌握情况"
        }
        """
        fake = _FakeOpenAI([payload])
        tutor = AITutor(api_key="test", client=fake)
        result = tutor.diagnose_question_turn(
            question={"section_title": "函数极限", "question_text": "求极限。"},
            original_user_answer="不会。",
            user_message="能出一道题测试我吗？",
            knowledge_tags=[],
            section_mastery={"attempts": 0, "accuracy": 0.0},
            weak_prerequisites=[],
            prerequisite_mastery=[],
            dialogue=[],
            support_results=[],
        )
        self.assertEqual(result["next_action"], "practice_same_section")

    def test_native_function_calling_returns_registered_tool_call(self) -> None:
        tutor = AITutor(
            api_key="test",
            client=_FakeNativeOpenAI(
                "search_prerequisite_questions",
                {"target_knowledge_id": "kp:derivative", "limit": 1},
            ),
        )
        result = tutor.diagnose_question_turn_native(
            question={"section_title": "导数", "question_text": "求导。"},
            original_user_answer="不会",
            user_message="先给我一道前置题",
            knowledge_tags=[],
            section_mastery={},
            weak_prerequisites=[],
            prerequisite_mastery=[],
            dialogue=[],
            support_results=[],
        )
        self.assertEqual(result["tool_name"], "search_prerequisite_questions")
        self.assertEqual(result["next_action"], "practice_prerequisite")

    def test_question_dialogue_summary_uses_only_dialogue_insights(self) -> None:
        payload = """
        {
          "stuck_point": "没有先寻找函数无定义点",
          "understood": "会先确定潜在间断点",
          "method": "先找定义域缺口，再逐点判断类型",
          "next_reminder": "不要直接计算极限，先检查定义域"
        }
        """
        fake = _FakeOpenAI([payload])
        tutor = AITutor(api_key="test", client=fake)
        summary = tutor.generate_question_dialogue_summary(
            section_title="函数极限",
            question_text="判断函数间断点。",
            answer_text="先找无定义点。",
            dialogue=[
                {"role": "user", "content": "我不知道先做什么。"},
                {"role": "assistant", "content": "先检查定义域。"},
            ],
        )
        self.assertIn("没有先寻找函数无定义点", summary["content"])
        self.assertEqual(summary["rating"], "")
        request = fake.completions.calls[0]["messages"][1]["content"]
        self.assertIn("我不知道先做什么", request)

    def test_question_dialogue_summary_saves_question_images(self) -> None:
        summary = {
            "content": "题目总结",
            "mastered": "已理解",
            "mistakes": "卡点",
            "insight": "方法",
            "next_suggestion": "提醒",
            "review_focus": "函数极限",
            "rating": "",
        }
        summary_id = database.save_question_dialogue_summary(
            summary,
            ["assets/question-bank/example.webp"],
        )
        saved = database.get_summary(summary_id)
        self.assertEqual(
            __import__("json").loads(saved["question_images_json"]),
            ["assets/question-bank/example.webp"],
        )

    def test_summary_uses_fixed_rating(self) -> None:
        summary_payload = """
        {
          "rating": "错误的模型评级",
          "largest_gap": "条件遗漏",
          "breakthrough": "能识别乘法公式结构",
          "retry_recommended": "是",
          "retry_reason": "需要巩固条件识别"
        }
        """
        tutor = AITutor(
            api_key="test",
            client=_FakeOpenAI([summary_payload]),
        )
        summary = tutor.generate_summary(
            self.context,
            [{"is_correct": True}] * 4 + [{"is_correct": False}],
        )
        self.assertEqual(summary["rating"], "🌊 深海探索者")
        self.assertIn("🌊 深海探索者", summary["content"])


if __name__ == "__main__":
    unittest.main()
