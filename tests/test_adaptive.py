from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import flowstudy.database as database
import flowstudy.react_agent as react_agent
from flowstudy.agent_eval import evaluate_agent_decision, evaluate_cases, load_eval_cases
from flowstudy.knowledge_catalog import nodes_for_section


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

    def test_catalog_has_prerequisites_and_specific_tags_keep_fallback(self) -> None:
        with database.connection() as conn:
            catalog_count = conn.execute(
                "SELECT COUNT(*) FROM knowledge_nodes WHERE source = 'curated'"
            ).fetchone()[0]
            prerequisite_count = conn.execute(
                "SELECT COUNT(*) FROM knowledge_prerequisites"
            ).fetchone()[0]
        self.assertGreater(catalog_count, 40)
        self.assertGreater(prerequisite_count, 20)

        question = database.get_question_bank_question("comprehensive-calculus-01-q001")
        self.assertIsNotNone(question)
        database.save_question_knowledge(
            question["id"],
            [
                {
                    "knowledge_id": "kp:calculus:derivative-definition",
                    "relation": "direct",
                    "confidence": 0.9,
                    "source": "test",
                }
            ],
        )
        tags = database.get_question_knowledge(question["id"])
        self.assertEqual(tags[0]["relation"], "direct")
        self.assertEqual(tags[0]["tag_source"], "test")
        self.assertTrue(any(tag["source"] == "section_fallback" for tag in tags))
        self.assertTrue(
            any(
                tag["title"] == "函数极限与连续性"
                and tag["relation"] == "prerequisite"
                and tag["tag_source"] == "curated_prerequisite"
                for tag in tags
            )
        )

    def test_section_title_overrides_conflicting_book_chapter_numbers(self) -> None:
        nodes = nodes_for_section(
            "calculus",
            3,
            "第3章 一元函数积分学及其应用 · 综合题",
        )
        titles = {node["title"] for node in nodes}
        self.assertIn("一元函数积分学的计算", titles)
        self.assertNotIn("中值定理", titles)

    def test_section_title_with_de_applies_maps_to_differential_calculus(self) -> None:
        nodes = nodes_for_section(
            "calculus",
            6,
            "第6章 一元函数微分学的应用（二）——中值定理、微分等式与微分不等式",
        )
        titles = {node["title"] for node in nodes}
        self.assertIn("中值定理", titles)
        self.assertNotIn("二重积分", titles)

    def test_react_knowledge_summary_separates_tag_relations(self) -> None:
        summary = react_agent._knowledge_summary(
            [
                {
                    "title": "导数与微分的定义",
                    "relation": "direct",
                    "tag_source": "ai_classifier",
                },
                {
                    "title": "函数极限与连续性",
                    "relation": "prerequisite",
                    "tag_source": "ai_classifier",
                },
                {
                    "title": "第2章 一元函数微分学及其应用",
                    "relation": "primary",
                    "tag_source": "section_fallback",
                },
            ]
        )
        self.assertIn("直接考点：导数与微分的定义", summary)
        self.assertIn("前置知识：函数极限与连续性", summary)
        self.assertIn("章节范围：第2章 一元函数微分学及其应用", summary)
        self.assertLess(summary.index("直接考点"), summary.index("前置知识"))
        self.assertLess(summary.index("前置知识"), summary.index("章节范围"))

    def test_weak_prerequisite_chooses_prerequisite_question(self) -> None:
        with database.connection() as conn:
            conn.execute(
                """
                INSERT INTO question_bank(
                    id, section_id, question_number, question_type,
                    question_text, question_images_json, answer_text,
                    answer_choice, answer_images_json, auto_gradable,
                    confidence, review_status, source_question_pages
                ) VALUES ('foundation-calculus-01-q002',
                          'foundation-calculus-01', 2, 'choice',
                          '前置题', '[]', '', 'A', '[]', 1,
                          1.0, 'verified', '1')
                """
            )
            conn.execute(
                """
                INSERT INTO question_knowledge(
                    question_id, knowledge_id, relation, confidence, source
                ) VALUES
                    ('comprehensive-calculus-01-q001',
                     'kp:calculus:derivative-definition',
                     'prerequisite', 0.9, 'test'),
                    ('foundation-calculus-01-q002',
                     'kp:calculus:derivative-definition',
                     'direct', 0.9, 'test')
                """
            )
            for answer in (0, 0):
                conn.execute(
                    """
                    INSERT INTO quiz_attempts(
                        question_id, day, knowledge_point, selected_answer,
                        is_correct, attempted_at, topic_id, attempt_type,
                        question_json
                    ) VALUES ('comprehensive-calculus-01-q001', 0, 'test',
                              'B', ?, '2026-01-01',
                              'comprehensive-calculus-01', 'test', '{}')
                    """,
                    (answer,),
                )
        original = database.get_question_bank_question(
            "comprehensive-calculus-01-q001"
        )
        self.assertIsNotNone(original)
        knowledge = react_agent.call_agent_tool(
            "inspect_question", {"question_id": original["id"]}
        )
        weak = react_agent._weak_prerequisites(knowledge)
        candidates = react_agent.call_agent_tool(
            "search_prerequisite_questions",
            {
                "target_knowledge_id": weak[0]["id"],
                "asked_ids": [original["id"]],
                "limit": 5,
            },
        )
        self.assertEqual(weak[0]["title"], "导数与微分的定义")
        self.assertEqual(candidates[0]["id"], "foundation-calculus-01-q002")
        self.assertEqual(candidates[0]["repair_scope"], "prerequisite")

    def test_daily_question_and_repair_candidates_use_fixed_bank(self) -> None:
        question = database.choose_daily_question()
        self.assertIsNotNone(question)
        candidates = database.choose_repair_questions(
            "comprehensive-calculus-01",
            ["comprehensive-calculus-01-q001"],
        )
        self.assertEqual(candidates[0]["phase"], "foundation")

    def test_tool_registry_validates_arguments_and_memory_is_persistent(self) -> None:
        with self.assertRaises(ValueError):
            react_agent.call_agent_tool("inspect_question", {})
        database.save_agent_memory(
            "preference",
            "hint_first",
            "用户偏好先获得提示。",
            source="test",
        )
        memories = database.get_agent_memories()
        self.assertEqual(memories[0]["memory_type"], "preference")
        self.assertEqual(memories[0]["content"], "用户偏好先获得提示。")
        database.clear_agent_memories()
        self.assertEqual(database.get_agent_memories(), [])

    def test_agent_eval_contract_covers_all_cases(self) -> None:
        decisions = {
            case["id"]: {
                "next_action": case["expected_action"],
                "tool_name": (
                    case["expected_tool"]
                    if case["expected_tool"] != "diagnose_question"
                    else None
                ),
            }
            for case in load_eval_cases()
        }
        report = evaluate_cases(decisions)
        self.assertEqual(report["passed"], report["total"])
        self.assertTrue(
            evaluate_agent_decision(
                {"next_action": "practice_prerequisite"},
                "practice_prerequisite",
                "search_prerequisite_questions",
            )["passed"]
        )

if __name__ == "__main__":
    unittest.main()
