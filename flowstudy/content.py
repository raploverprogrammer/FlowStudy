from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from flowstudy.config import BASE_DIR


TOPICS_PATH = BASE_DIR / "content" / "topics.json"
KNOWLEDGE_TREE_PATH = BASE_DIR / "content" / "knowledge_tree.json"


@lru_cache(maxsize=1)
def get_topics() -> list[dict[str, Any]]:
    """Return the legacy local question bank."""
    with TOPICS_PATH.open("r", encoding="utf-8") as file:
        topics = json.load(file)
    _validate_topics(topics)
    return topics


@lru_cache(maxsize=1)
def get_topic_tree() -> list[dict[str, Any]]:
    """Return the seven user-visible postgraduate probability chapters."""
    with KNOWLEDGE_TREE_PATH.open("r", encoding="utf-8") as file:
        tree = json.load(file)
    _validate_topic_tree(tree)
    return tree


def _validate_topics(topics: list[dict[str, Any]]) -> None:
    topic_ids: set[str] = set()
    question_ids: set[str] = set()
    required = {
        "id",
        "topic",
        "difficulty",
        "core_concepts",
        "classic_patterns",
        "goal",
        "concept",
        "questions",
    }
    for topic in topics:
        missing = required - topic.keys()
        if missing:
            raise ValueError(f"Topic {topic.get('id')} 缺少字段: {sorted(missing)}")
        if topic["id"] in topic_ids:
            raise ValueError(f"重复 Topic ID: {topic['id']}")
        topic_ids.add(topic["id"])

        diagnostic_count = 0
        for question in topic["questions"]:
            if question["id"] in question_ids:
                raise ValueError(f"重复题目 ID: {question['id']}")
            question_ids.add(question["id"])
            diagnostic_count += question["phase"] == "diagnostic"
            if not question["answer"]:
                raise ValueError(f"题目 {question['id']} 没有答案")
            if max(question["answer"]) >= len(question["options"]):
                raise ValueError(f"题目 {question['id']} 答案索引越界")
        if diagnostic_count != 3:
            raise ValueError(f"Topic {topic['id']} 必须恰好有 3 道诊断题")


def _validate_topic_tree(tree: list[dict[str, Any]]) -> None:
    if len(tree) != 7:
        raise ValueError("概率论 Knowledge Tree 必须包含 7 个章节")
    required = {
        "id",
        "order",
        "title",
        "introduction",
        "core_concepts",
        "high_frequency_points",
        "source_pdf",
    }
    ids = [chapter["id"] for chapter in tree]
    if len(set(ids)) != len(ids):
        raise ValueError("Knowledge Tree 章节 ID 重复")
    for chapter in tree:
        missing = required - chapter.keys()
        if missing:
            raise ValueError(f"章节 {chapter.get('id')} 缺少字段: {sorted(missing)}")
    if [chapter["order"] for chapter in tree] != list(range(1, 8)):
        raise ValueError("Knowledge Tree 章节顺序必须为 1 到 7")


def get_lesson(lesson_id: str) -> dict[str, Any]:
    for lesson in get_topic_tree():
        if lesson["id"] == lesson_id:
            return lesson
    raise KeyError(f"未知讲次: {lesson_id}")


def get_topic(topic_id: str) -> dict[str, Any]:
    """Return a chapter or a legacy local question-bank topic."""
    for chapter in get_topic_tree():
        if chapter["id"] == topic_id:
            return {
                **chapter,
                "topic": chapter["title"],
                "questions": [],
            }
    for topic in get_topics():
        if topic["id"] == topic_id:
            return topic
    raise KeyError(f"未知题库 Topic: {topic_id}")


def get_question(question_id: str) -> dict[str, Any] | None:
    for topic in get_topics():
        for question in topic["questions"]:
            if question["id"] == question_id:
                return question
    legacy = re.fullmatch(r"d([1-7])q([1-3])", question_id)
    if legacy:
        topic_index = int(legacy.group(1)) - 1
        question_index = int(legacy.group(2)) - 1
        return questions_for(get_topics()[topic_index], "diagnostic")[question_index]
    return None


def questions_for(topic: dict[str, Any], phase: str) -> list[dict[str, Any]]:
    return [question for question in topic["questions"] if question["phase"] == phase]


@lru_cache(maxsize=1)
def get_concepts() -> list[dict[str, Any]]:
    return [
        {
            "id": chapter["id"],
            "topic_id": chapter["id"],
            "topic": chapter["title"],
            "concept": chapter["title"],
            "path": [chapter["title"]],
            "breadcrumb": chapter["title"],
            "has_children": False,
            "introduction": chapter["introduction"],
            "core_concepts": chapter["core_concepts"],
            "high_frequency_points": chapter["high_frequency_points"],
        }
        for chapter in get_topic_tree()
    ]


def get_concept(concept_key: str) -> dict[str, Any]:
    for concept in get_concepts():
        if concept["id"] == concept_key:
            return concept
    raise KeyError(f"未知 Concept: {concept_key}")


def concepts_for_lesson(lesson_id: str) -> list[dict[str, Any]]:
    return [concept for concept in get_concepts() if concept["id"] == lesson_id]


def concept_for_question(
    topic: dict[str, Any], question: dict[str, Any]
) -> dict[str, Any]:
    chapter_by_bank = {
        "random-events": "chapter-1",
        "probability-definition": "chapter-1",
        "classical-probability": "chapter-1",
        "conditional-probability": "chapter-1",
        "independence": "chapter-1",
        "total-probability": "chapter-1",
        "bayes": "chapter-1",
        "random-variable": "chapter-2",
        "distribution-function": "chapter-2",
        "expectation": "chapter-4",
        "variance": "chapter-4",
    }
    return get_concept(chapter_by_bank.get(topic["id"], "chapter-1"))


def questions_for_concept(concept_key: str) -> list[dict[str, Any]]:
    concept = get_concept(concept_key)
    matched: list[dict[str, Any]] = []
    for topic in get_topics():
        for question in topic["questions"]:
            if concept_for_question(topic, question)["id"] == concept_key:
                matched.append(question)
    if matched:
        return matched

    fallback_topic_ids = {
        "chapter-1": [
            "random-events",
            "probability-definition",
            "classical-probability",
            "conditional-probability",
            "independence",
            "total-probability",
            "bayes",
        ],
        "chapter-2": ["random-variable", "distribution-function"],
        "chapter-3": ["distribution-function", "random-variable"],
        "chapter-4": ["expectation", "variance"],
        "chapter-5": ["expectation", "variance"],
        "chapter-6": ["expectation", "variance"],
        "chapter-7": ["expectation", "variance"],
    }
    questions: list[dict[str, Any]] = []
    for topic_id in fallback_topic_ids[concept["topic_id"]]:
        questions.extend(get_topic(topic_id)["questions"])
    return questions
