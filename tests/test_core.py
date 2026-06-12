from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import flowstudy.database as database
import flowstudy.views as views
from services.ai_service import AITutor
from flowstudy.views import _markdown_math, _plain_math
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

    def test_route_helpers_follow_question_bank_order(self) -> None:
        sections = [
            {"id": "foundation-calculus-01", "attempts": 5, "correct_attempts": 3},
            {"id": "foundation-calculus-02", "attempts": 0, "correct_attempts": 0},
        ]
        self.assertEqual(
            views._first_unexplored_section_id(sections),
            "foundation-calculus-02",
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

    def test_question_bank_only_exposes_calculus(self) -> None:
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
            ["calculus-section"],
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
