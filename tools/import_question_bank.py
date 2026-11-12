from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
from PIL import Image
from rapidocr_onnxruntime import RapidOCR


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "flowstudy.db"
ASSET_ROOT = ROOT / "data" / "question_bank"
MANIFEST_PATH = ASSET_ROOT / "manifest.json"
ACTIVE_SUBJECTS = {"calculus"}

SUBJECT_NAMES = {
    "calculus": "高等数学",
    "linear_algebra": "线性代数",
    "probability": "概率论与数理统计",
    "comprehensive": "综合训练",
}
PHASE_NAMES = {
    "foundation": "基础篇",
    "enhancement": "强化篇",
    "comprehensive": "综合篇",
}

# The analysis book has no PDF bookmarks. These starts were read from its
# printed contents and verified against sampled chapter title pages.
ANALYSIS_STARTS = {
    ("foundation", "calculus"): [
        9, 14, 20, 23, 28, 33, 41, 48, 49, 59,
        75, 81, 86, 89, 97, 105, 111, 118, 122,
    ],
    ("foundation", "linear_algebra"): [128, 133, 138, 143, 150, 162],
    ("foundation", "probability"): [179, 183, 186, 194, 203, 206],
    ("enhancement", "calculus"): [
        217, 229, 233, 241, 245, 259, 267, 268, 276,
        285, 296, 300, 302, 318, 339, 354, 373, 379,
    ],
    ("enhancement", "linear_algebra"): [
        395, 400, 401, 405, 408, 418, 423, 427, 440,
    ],
    ("enhancement", "probability"): [
        458, 461, 465, 469, 473, 482, 494, 496, 501,
    ],
    ("comprehensive", "comprehensive"): [523, 533, 544, 558],
}

BATCH_FOR = {
    ("foundation", "calculus"): 1,
    ("foundation", "linear_algebra"): 2,
    ("foundation", "probability"): 3,
    ("enhancement", "calculus"): 4,
    ("enhancement", "linear_algebra"): 4,
    ("enhancement", "probability"): 4,
    ("comprehensive", "comprehensive"): 5,
}

QUESTION_START = re.compile(r"^\s*(\d{1,3})\s*[.．、]\s*(.*)")
ANSWER_START = re.compile(
    r"^\s*(\d{1,3})\s*[.．、]?\s*【\s*答案\s*】\s*(.*)"
)
EXPLANATION_START = re.compile(
    r"^\s*(\d{1,3})\s*[.．、]?\s*【\s*解析\s*】\s*(.*)"
)
CHOICE_ANSWER = re.compile(r"[\(（]?\s*([ABCD])\s*[\)）]?")


@dataclass
class Section:
    id: str
    batch: int
    phase: str
    subject: str
    chapter_number: int
    title: str
    question_start: int
    question_end: int
    answer_start: int
    answer_end: int


@dataclass
class OCRLine:
    x: float
    y: float
    bottom: float
    text: str
    confidence: float


def locate_books() -> tuple[Path, Path]:
    candidates = [
        path
        for path in (Path.home() / "Desktop").glob("*.pdf")
        if path.stat().st_size > 50_000_000
    ]
    if len(candidates) < 2:
        raise FileNotFoundError("桌面未找到试题册和解析册 PDF")
    question_book = max(candidates, key=lambda path: path.stat().st_size)
    answer_book = min(candidates, key=lambda path: path.stat().st_size)
    return question_book, answer_book


def clean_title(title: str) -> str:
    return re.sub(r"\s+", "", title).replace("叽何", "几何").replace("三J", "三")


def build_sections(question_book: Path, answer_pages: int) -> list[Section]:
    document = fitz.open(question_book)
    toc = document.get_toc()
    document.close()
    phase = ""
    subject = ""
    grouped: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for level, title, page in toc:
        normalized = clean_title(title)
        if level == 1:
            if "基础篇" in normalized:
                phase = "foundation"
            elif "强化篇" in normalized:
                phase = "enhancement"
            elif "综合篇" in normalized:
                phase = "comprehensive"
            continue
        if level == 2:
            if "高数" in normalized:
                subject = "calculus"
            elif "线代" in normalized:
                subject = "linear_algebra"
            elif "概率" in normalized:
                subject = "probability"
            elif "测试卷" in normalized:
                subject = "comprehensive"
                grouped.setdefault((phase, subject), []).append((normalized, page))
            continue
        if level == 3 and phase and subject:
            grouped.setdefault((phase, subject), []).append((normalized, page))

    # The warm-up section is a real part of the book and precedes chapter 1.
    basic_calculus = grouped[("foundation", "calculus")]
    if not basic_calculus or "零基础" not in basic_calculus[0][0]:
        basic_calculus.insert(0, ("零基础热身", 9))

    flat_question_starts = sorted(
        page for values in grouped.values() for _, page in values
    )
    question_next = {
        page: (
            flat_question_starts[index + 1] - 1
            if index + 1 < len(flat_question_starts)
            else 195
        )
        for index, page in enumerate(flat_question_starts)
    }

    sections: list[Section] = []
    for key, values in grouped.items():
        starts = ANALYSIS_STARTS[key]
        if len(starts) != len(values):
            raise ValueError(
                f"{key} 目录数量不一致：试题册 {len(values)}，解析册 {len(starts)}"
            )
        for index, ((title, question_start), answer_start) in enumerate(
            zip(values, starts, strict=True)
        ):
            next_answer = (
                starts[index + 1] - 1
                if index + 1 < len(starts)
                else _next_analysis_group_start(key, answer_pages) - 1
            )
            chapter_number_match = re.search(r"第(\d+)章", title)
            chapter_number = (
                int(chapter_number_match.group(1))
                if chapter_number_match
                else (0 if "零基础" in title else index + 1)
            )
            section_id = (
                f"{key[0]}-{key[1]}-{chapter_number:02d}"
                if "零基础" not in title
                else "foundation-calculus-00"
            )
            sections.append(
                Section(
                    id=section_id,
                    batch=BATCH_FOR[key],
                    phase=key[0],
                    subject=key[1],
                    chapter_number=chapter_number,
                    title=title,
                    question_start=question_start,
                    question_end=question_next[question_start],
                    answer_start=answer_start,
                    answer_end=max(answer_start, next_answer),
                )
            )
    return sorted(
        sections,
        key=lambda section: (
            section.batch,
            section.subject,
            section.chapter_number,
        ),
    )


def _next_analysis_group_start(
    key: tuple[str, str],
    answer_pages: int,
) -> int:
    ordered = list(ANALYSIS_STARTS)
    index = ordered.index(key)
    if index + 1 < len(ordered):
        return ANALYSIS_STARTS[ordered[index + 1]][0]
    return answer_pages + 1


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS question_bank_sections (
            id TEXT PRIMARY KEY,
            batch INTEGER NOT NULL,
            phase TEXT NOT NULL,
            subject TEXT NOT NULL,
            chapter_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            question_page_start INTEGER NOT NULL,
            question_page_end INTEGER NOT NULL,
            answer_page_start INTEGER NOT NULL,
            answer_page_end INTEGER NOT NULL,
            question_count INTEGER NOT NULL DEFAULT 0,
            verified_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS question_bank (
            id TEXT PRIMARY KEY,
            section_id TEXT NOT NULL,
            question_number INTEGER NOT NULL,
            question_type TEXT NOT NULL,
            question_text TEXT NOT NULL DEFAULT '',
            question_images_json TEXT NOT NULL,
            answer_text TEXT NOT NULL DEFAULT '',
            answer_choice TEXT,
            answer_images_json TEXT NOT NULL DEFAULT '[]',
            auto_gradable INTEGER NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 0,
            review_status TEXT NOT NULL DEFAULT 'needs_review',
            source_question_pages TEXT NOT NULL,
            source_page_images_json TEXT NOT NULL DEFAULT '[]',
            source_answer_pages TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(section_id) REFERENCES question_bank_sections(id),
            UNIQUE(section_id, question_number)
        );

        CREATE INDEX IF NOT EXISTS idx_question_bank_section
        ON question_bank(section_id, question_number);

        CREATE TABLE IF NOT EXISTS question_bank_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch INTEGER NOT NULL,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT,
            sections INTEGER NOT NULL DEFAULT 0,
            questions INTEGER NOT NULL DEFAULT 0,
            matched_answers INTEGER NOT NULL DEFAULT 0,
            auto_gradable INTEGER NOT NULL DEFAULT 0,
            needs_review INTEGER NOT NULL DEFAULT 0,
            report_json TEXT NOT NULL DEFAULT '{}'
        );
        """
    )


def ocr_page(
    document: fitz.Document,
    page_number: int,
    engine: RapidOCR,
    scale: float = 1.8,
) -> tuple[Image.Image, list[OCRLine]]:
    pixmap = document[page_number - 1].get_pixmap(
        matrix=fitz.Matrix(scale, scale),
        alpha=False,
    )
    png = pixmap.tobytes("png")
    image = Image.open(__import__("io").BytesIO(png)).convert("RGB")
    result, _ = engine(png)
    lines: list[OCRLine] = []
    for box, text, confidence in result or []:
        lines.append(
            OCRLine(
                x=min(point[0] for point in box),
                y=min(point[1] for point in box),
                bottom=max(point[1] for point in box),
                text=str(text).strip(),
                confidence=float(confidence),
            )
        )
    lines.sort(key=lambda line: (line.y, line.x))
    return image, lines


def question_starts(lines: list[OCRLine], image_width: int) -> list[tuple[int, OCRLine]]:
    starts: list[tuple[int, OCRLine]] = []
    for line in lines:
        match = QUESTION_START.match(line.text)
        if (
            match
            and line.x < image_width * 0.24
            and line.confidence >= 0.55
            and 1 <= int(match.group(1)) <= 300
        ):
            starts.append((int(match.group(1)), line))
    return starts


def crop_path(section: Section, kind: str, number: int, suffix: int) -> Path:
    directory = ASSET_ROOT / section.id / kind
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"q{number:03d}-{suffix:02d}.webp"


def save_crop(
    image: Image.Image,
    box: tuple[int, int, int, int],
    path: Path,
) -> str:
    cropped = image.crop(box)
    cropped.save(path, "WEBP", quality=92, method=6)
    return path.relative_to(ROOT).as_posix()


def source_page_path(section: Section, page_number: int) -> Path:
    directory = ASSET_ROOT / section.id / "source_pages"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"page-{page_number:03d}.webp"


def save_source_page(
    image: Image.Image,
    section: Section,
    page_number: int,
) -> str:
    """Persist the complete rendered source page without a question crop."""
    path = source_page_path(section, page_number)
    if not path.exists():
        image.save(path, "WEBP", quality=96, method=6)
    return path.relative_to(ROOT).as_posix()


def extract_questions(
    document: fitz.Document,
    section: Section,
    engine: RapidOCR,
) -> dict[int, dict[str, Any]]:
    questions: dict[int, dict[str, Any]] = {}
    active_number: int | None = None
    highest_number = 0
    for page_number in range(section.question_start, section.question_end + 1):
        # Formula-only questions are easy to miss at the lighter answer-book
        # OCR scale. A 3x render reliably preserves their small leading number
        # and also produces a crisp source crop for the learning interface.
        image, lines = ocr_page(document, page_number, engine, scale=3.0)
        source_page = save_source_page(image, section, page_number)
        body_top = int(image.height * 0.12)
        body_bottom = int(image.height * 0.94)
        raw_starts = [
            (number, line)
            for number, line in question_starts(lines, image.width)
            if body_top <= line.y < body_bottom - 40
        ]
        starts: list[tuple[int, OCRLine]] = []
        previous_y = float(body_top)
        for number, line in raw_starts:
            if number <= highest_number:
                continue
            if highest_number == 0 and number > 5:
                continue
            if highest_number and number > highest_number + 8:
                continue
            missing_count = number - highest_number - 1
            if 0 < missing_count <= 4:
                step = (line.y - previous_y) / (missing_count + 1)
                for offset in range(1, missing_count + 1):
                    missing_number = highest_number + offset
                    starts.append(
                        (
                            missing_number,
                            OCRLine(
                                x=line.x,
                                y=previous_y + step * offset,
                                bottom=previous_y + step * offset + 20,
                                text=f"{missing_number}.",
                                confidence=0.30,
                            ),
                        )
                    )
            starts.append((number, line))
            highest_number = number
            previous_y = line.y
        if not starts:
            if active_number is not None:
                record = questions[active_number]
                record.setdefault("source_page_images", []).append(source_page)
                path = crop_path(
                    section, "questions", active_number, len(record["images"]) + 1
                )
                record["images"].append(
                    save_crop(
                        image,
                        (int(image.width * 0.07), body_top,
                         int(image.width * 0.94), body_bottom),
                        path,
                    )
                )
                record["pages"].append(page_number)
                record["text"].extend(line.text for line in lines)
            continue

        first_y = max(body_top, int(starts[0][1].y) - 14)
        if active_number is not None and first_y > body_top + 30:
            record = questions[active_number]
            record.setdefault("source_page_images", []).append(source_page)
            path = crop_path(
                section, "questions", active_number, len(record["images"]) + 1
            )
            record["images"].append(
                save_crop(
                    image,
                    (int(image.width * 0.07), body_top,
                     int(image.width * 0.94), first_y),
                    path,
                )
            )
            record["pages"].append(page_number)
            record["text"].extend(
                line.text for line in lines if body_top <= line.y < first_y
            )

        for index, (number, start_line) in enumerate(starts):
            top = max(body_top, int(start_line.y) - 14)
            bottom = (
                max(top + 40, int(starts[index + 1][1].y) - 14)
                if index + 1 < len(starts)
                else body_bottom
            )
            active_number = number
            record = questions.setdefault(
                number,
                {
                    "images": [],
                    "pages": [],
                    "source_page_images": [],
                    "text": [],
                    "confidence": [],
                },
            )
            record["source_page_images"].append(source_page)
            path = crop_path(
                section, "questions", number, len(record["images"]) + 1
            )
            record["images"].append(
                save_crop(
                    image,
                    (int(image.width * 0.07), top,
                     int(image.width * 0.94), bottom),
                    path,
                )
            )
            record["pages"].append(page_number)
            selected_lines = [line for line in lines if top <= line.y < bottom]
            record["text"].extend(line.text for line in selected_lines)
            record["confidence"].extend(line.confidence for line in selected_lines)

    for record in questions.values():
        text = "\n".join(record["text"])
        if re.search(r"\([A-D]\)|（[A-D]）", text):
            question_type = "choice"
        elif "证明" in text or "求证" in text:
            question_type = "proof"
        else:
            question_type = "calculation"
        record["question_type"] = question_type
        record["question_text"] = text
        record["ocr_confidence"] = (
            sum(record["confidence"]) / len(record["confidence"])
            if record["confidence"]
            else 0.0
        )
    return questions


def extract_answers(
    document: fitz.Document,
    section: Section,
    engine: RapidOCR,
    expected_numbers: set[int],
) -> dict[int, dict[str, Any]]:
    answers: dict[int, dict[str, Any]] = {}
    active_number: int | None = None
    page_cache: dict[int, tuple[Image.Image, list[OCRLine]]] = {}
    for page_number in range(section.answer_start, section.answer_end + 1):
        image, lines = ocr_page(document, page_number, engine)
        page_cache[page_number] = (image, lines)
        for line in lines:
            answer_match = ANSWER_START.match(line.text)
            explanation_match = EXPLANATION_START.match(line.text)
            if answer_match:
                number = int(answer_match.group(1))
                active_number = number
                answers.setdefault(
                    number,
                    {
                        "answer_text": "",
                        "answer_confidence": 0.0,
                        "images": [],
                        "pages": [],
                        "start": (page_number, line.y),
                    },
                )
                answers[number]["answer_text"] = answer_match.group(2).strip()
                answers[number]["answer_confidence"] = line.confidence
            elif explanation_match:
                number = int(explanation_match.group(1))
                active_number = number
                answers.setdefault(
                    number,
                    {
                        "answer_text": "",
                        "answer_confidence": 0.0,
                        "images": [],
                        "pages": [],
                        "start": (page_number, line.y),
                    },
                )
            elif active_number is not None:
                answers[active_number].setdefault("text", []).append(line.text)

    known_numbers = sorted(answers)
    if expected_numbers and known_numbers:
        first_page_image = page_cache[section.answer_start][0]
        last_page_image = page_cache[section.answer_end][0]

        def absolute_position(page: int, y: float) -> float:
            return (page - section.answer_start) * first_page_image.height + y

        def page_position(value: float) -> tuple[int, float]:
            page_offset, y = divmod(max(0.0, value), first_page_image.height)
            page = min(section.answer_end, section.answer_start + int(page_offset))
            return page, y

        for number in sorted(expected_numbers - set(answers)):
            previous = max((value for value in known_numbers if value < number), default=None)
            following = min((value for value in known_numbers if value > number), default=None)
            if previous is not None:
                previous_start = answers[previous]["start"]
                previous_position = absolute_position(*previous_start)
            else:
                previous = 0
                previous_position = float(first_page_image.height * 0.10)
            if following is not None:
                following_start = answers[following]["start"]
                following_position = absolute_position(*following_start)
            else:
                following = max(expected_numbers) + 1
                following_position = absolute_position(
                    section.answer_end,
                    float(last_page_image.height * 0.94),
                )
            fraction = (number - previous) / max(1, following - previous)
            synthetic_position = (
                previous_position
                + (following_position - previous_position) * fraction
            )
            answers[number] = {
                "answer_text": "",
                "answer_confidence": 0.0,
                "images": [],
                "pages": [],
                "start": page_position(synthetic_position),
                "text": [],
            }

    ordered = sorted(
        (
            number,
            value["start"][0],
            value["start"][1],
        )
        for number, value in answers.items()
    )
    for index, (number, page_number, y) in enumerate(ordered):
        next_page, next_y = (
            (ordered[index + 1][1], ordered[index + 1][2])
            if index + 1 < len(ordered)
            else (section.answer_end, None)
        )
        for current_page in range(page_number, next_page + 1):
            image, _ = page_cache[current_page]
            top = int(y) - 12 if current_page == page_number else int(image.height * 0.1)
            bottom = (
                int(next_y) - 12
                if current_page == next_page and next_y is not None
                else int(image.height * 0.94)
            )
            if bottom <= top + 20:
                continue
            record = answers[number]
            path = crop_path(
                section, "answers", number, len(record["images"]) + 1
            )
            record["images"].append(
                save_crop(
                    image,
                    (int(image.width * 0.07), top,
                     int(image.width * 0.94), bottom),
                    path,
                )
            )
            record["pages"].append(current_page)
    return answers


def normalize_answer(
    question_type: str,
    answer: dict[str, Any] | None,
) -> tuple[str, str | None, bool, float]:
    if not answer:
        return "", None, False, 0.0
    text = str(answer.get("answer_text", "")).strip()
    confidence = float(answer.get("answer_confidence", 0.0))
    if question_type == "choice":
        match = CHOICE_ANSWER.fullmatch(text) or CHOICE_ANSWER.search(text)
        if match and confidence >= 0.60:
            return text, match.group(1), True, confidence
        return text, None, False, confidence
    if question_type == "proof":
        return text, None, False, confidence
    safe = bool(
        text
        and len(text) <= 48
        and confidence >= 0.78
        and not re.search(r"[【】解析]", text)
    )
    return text, None, safe, confidence


def import_section(
    conn: sqlite3.Connection,
    question_document: fitz.Document,
    answer_document: fitz.Document,
    section: Section,
    engine: RapidOCR,
) -> dict[str, int]:
    print(
        f"[{section.batch}] {PHASE_NAMES[section.phase]} / "
        f"{SUBJECT_NAMES[section.subject]} / {section.title}"
    )
    questions = extract_questions(question_document, section, engine)
    answers = extract_answers(
        answer_document,
        section,
        engine,
        set(questions),
    )
    conn.execute(
        """
        INSERT INTO question_bank_sections(
            id, batch, phase, subject, chapter_number, title,
            question_page_start, question_page_end,
            answer_page_start, answer_page_end
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            batch=excluded.batch,
            phase=excluded.phase,
            subject=excluded.subject,
            chapter_number=excluded.chapter_number,
            title=excluded.title,
            question_page_start=excluded.question_page_start,
            question_page_end=excluded.question_page_end,
            answer_page_start=excluded.answer_page_start,
            answer_page_end=excluded.answer_page_end,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            section.id, section.batch, section.phase, section.subject,
            section.chapter_number, section.title,
            section.question_start, section.question_end,
            section.answer_start, section.answer_end,
        ),
    )
    conn.execute("DELETE FROM question_bank WHERE section_id = ?", (section.id,))
    matched = 0
    gradable = 0
    reviewed = 0
    for number, question in sorted(questions.items()):
        answer = answers.get(number)
        answer_text, answer_choice, auto_gradable, answer_confidence = (
            normalize_answer(question["question_type"], answer)
        )
        matched += bool(answer)
        gradable += auto_gradable
        confidence = min(
            float(question["ocr_confidence"]),
            answer_confidence if answer else 0.0,
        )
        review_status = (
            "verified"
            if auto_gradable and confidence >= 0.82
            else "needs_review"
        )
        reviewed += review_status == "needs_review"
        conn.execute(
            """
            INSERT INTO question_bank(
                id, section_id, question_number, question_type,
                question_text, question_images_json,
                answer_text, answer_choice, answer_images_json,
                auto_gradable, confidence, review_status,
                source_question_pages, source_page_images_json,
                source_answer_pages
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{section.id}-q{number:03d}",
                section.id,
                number,
                question["question_type"],
                question["question_text"],
                json.dumps(question["images"], ensure_ascii=False),
                answer_text,
                answer_choice,
                json.dumps(
                    answer.get("images", []) if answer else [],
                    ensure_ascii=False,
                ),
                int(auto_gradable),
                confidence,
                review_status,
                ",".join(map(str, sorted(set(question["pages"])))),
                json.dumps(
                    list(dict.fromkeys(question.get("source_page_images", []))),
                    ensure_ascii=False,
                ),
                ",".join(
                    map(str, sorted(set(answer.get("pages", []))))
                    if answer else []
                ),
            ),
        )
    conn.execute(
        """
        UPDATE question_bank_sections
        SET question_count = ?, verified_count = ?, updated_at=CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (len(questions), len(questions) - reviewed, section.id),
    )
    conn.commit()
    return {
        "questions": len(questions),
        "matched_answers": matched,
        "auto_gradable": gradable,
        "needs_review": reviewed,
    }


def write_manifest(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, batch, phase, subject, chapter_number, title,
               question_count, verified_count
        FROM question_bank_sections
        ORDER BY batch, subject, chapter_number
        """
    ).fetchall()
    manifest = [
        {
            "id": row[0],
            "batch": row[1],
            "phase": row[2],
            "subject": row[3],
            "chapter_number": row[4],
            "title": row[5],
            "question_count": row[6],
            "verified_count": row[7],
        }
        for row in rows
    ]
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, choices=(1, 4))
    parser.add_argument("--section")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    question_book, answer_book = locate_books()
    answer_document = fitz.open(answer_book)
    sections = build_sections(question_book, len(answer_document))
    if args.list:
        for section in sections:
            print(section)
        answer_document.close()
        return

    selected = [
        section for section in sections
        if section.subject in ACTIVE_SUBJECTS
        and (args.batch is None or section.batch == args.batch)
        and (args.section is None or section.id == args.section)
    ]
    if args.section and not selected:
        raise ValueError(f"Unknown section: {args.section}")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    init_schema(connection)
    cursor = connection.execute(
        "INSERT INTO question_bank_imports(batch) VALUES (?)",
        (args.batch or 0,),
    )
    import_id = cursor.lastrowid
    connection.commit()
    question_document = fitz.open(question_book)
    engine = RapidOCR()
    totals = {
        "sections": 0,
        "questions": 0,
        "matched_answers": 0,
        "auto_gradable": 0,
        "needs_review": 0,
    }
    reports: dict[str, Any] = {}
    try:
        for section in selected:
            report = import_section(
                connection,
                question_document,
                answer_document,
                section,
                engine,
            )
            reports[section.id] = report
            totals["sections"] += 1
            for key in report:
                totals[key] += report[key]
        write_manifest(connection)
        connection.execute(
            """
            UPDATE question_bank_imports
            SET finished_at=CURRENT_TIMESTAMP, sections=?, questions=?,
                matched_answers=?, auto_gradable=?, needs_review=?,
                report_json=?
            WHERE id=?
            """,
            (
                totals["sections"],
                totals["questions"],
                totals["matched_answers"],
                totals["auto_gradable"],
                totals["needs_review"],
                json.dumps(reports, ensure_ascii=False),
                import_id,
            ),
        )
        connection.commit()
    finally:
        question_document.close()
        answer_document.close()
        connection.close()
    print(json.dumps(totals, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
