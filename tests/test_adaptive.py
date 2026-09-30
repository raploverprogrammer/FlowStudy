from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import flowstudy.database as database
import flowstudy.react_agent as react_agent


class AdaptiveFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = database.DB_PATH
        database.DB_PATH = Path(self.temp_dir.name) / "adaptive.db"
        database.init_db()
        with database.connection() as conn:
            conn.execute(
                """
                INSERT INTO question_bank_sections(
                    id, batch, phase, subject, chapter_number, title,
                    question_page_start, question_page_end,
                    answer_page_start, answer_page_end, question_count
                ) VALUES
                    ('foundation-calculus-01', 1, 'foundation', 'calculus', 1,
                     '高等数学第一章基础题', 1, 1, 1, 1, 1),
                    ('comprehensive-calculus-01', 1, 'comprehensive', 'calculus', 1,
                     '高等数学第一章综合题', 1, 1, 1, 1, 1)
                """
            )
            for question_id, section_id, number in (
                ("foundation-calculus-01-q001", "foundation-calculus-01", 1),
                ("comprehensive-calculus-01-q001", "comprehensive-calculus-01", 1),
            ):
                conn.execute(
                    """
                    INSERT INTO question_bank(
                        id, section_id, question_number, question_type,
                        question_text, question_images_json, answer_text,
                        answer_choice, answer_images_json, auto_gradable,
                        confidence, review_status, source_question_pages
                    ) VALUES (?, ?, ?, 'choice', ?, '[]', '', 'A', '[]', 1,
                              1.0, 'verified', '1')
                    """,
                    (question_id, section_id, number, f"题目 {question_id}"),
                )
        database.init_db()

    def tearDown(self) -> None:
        database.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_every_question_gets_internal_knowledge_tag(self) -> None:
        question = database.get_question_bank_question("comprehensive-calculus-01-q001")
        self.assertIsNotNone(question)
        tags = database.get_question_knowledge(question["id"])
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0]["relation"], "primary")

    def test_daily_question_and_repair_candidates_use_fixed_bank(self) -> None:
        question = database.choose_daily_question()
        self.assertIsNotNone(question)
        candidates = database.choose_repair_questions(
            "comprehensive-calculus-01",
            ["comprehensive-calculus-01-q001"],
        )
        self.assertEqual(candidates[0]["phase"], "foundation")

    def test_react_fallback_returns_to_original_after_support_answer(self) -> None:
        question = database.get_question_bank_question("comprehensive-calculus-01-q001")
        self.assertIsNotNone(question)
        with patch.object(react_agent, "AITutor", _OfflineTutor):
            progress: list[str] = []
            daily_id = database.start_daily_session(question["id"], {})
            state = react_agent.start_repair(
                daily_session_id=daily_id,
                original_question=question,
                original_user_answer="B",
                asked_ids=[question["id"]],
                progress=progress.append,
            )
            self.assertEqual(state["status"], "repair")
            self.assertTrue(any(message.startswith("**观察**：") for message in progress))
            self.assertTrue(any(message.startswith("**行动**：") for message in progress))
            self.assertGreaterEqual(len(state["trace"]), 6)
            support = state["current_question"]
            state = react_agent.advance_repair(
                state=state,
                support_question=support,
                user_answer="A",
                is_correct=True,
                progress=progress.append,
            )
            self.assertEqual(state["status"], "original_retest")
            report = react_agent.finish_repair(
                state=state,
                original_retest_correct=True,
                progress=progress.append,
            )
            self.assertIn("补充题", report["content"])
            self.assertTrue(
                any("补充题" in event["message"] for event in state["trace"])
            )
            self.assertTrue(
                any("报告已生成，补课记录已保存。" in message for message in progress)
            )


class _OfflineTutor:
    enabled = False


if __name__ == "__main__":
    unittest.main()
