from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import fitz
from PIL import Image
from rapidocr_onnxruntime import RapidOCR


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "flowstudy.db"
ASSET_ROOT = ROOT / "data" / "question_bank" / "lilin880"
SOURCE = "lilin880"
SOURCE_LABEL = "李林880题"
ANSWER_PAGE_OFFSET = 6

PHASES = {
    "基础题": "foundation",
    "综合题": "comprehensive",
    "拓展题": "extension",
}
PHASE_LABELS = {value: key for key, value in PHASES.items()}
SUBJECT_LABELS = {
    "calculus": "高等数学",
    "linear_algebra": "线性代数",
    "probability": "概率论与数理统计",
}
TYPE_LABELS = {
    "choice": "选择题",
    "fill": "填空题",
    "calculation": "解答题",
}

# Printed-page starts read from the official analysis book contents.
ANSWER_STARTS: dict[int, dict[str, int]] = {
    1: {"foundation": 1, "comprehensive": 7, "extension": 19},
    2: {"foundation": 21, "comprehensive": 35, "extension": 49},
    3: {"foundation": 52, "comprehensive": 68, "extension": 91},
    4: {"foundation": 101, "extension": 106},
    5: {"foundation": 108, "comprehensive": 116, "extension": 127},
    6: {"foundation": 129, "comprehensive": 141, "extension": 154},
    7: {"foundation": 157, "comprehensive": 163, "extension": 174},
    8: {"foundation": 177, "comprehensive": 187, "extension": 199},
    9: {"foundation": 201, "comprehensive": 210, "extension": 228},
    10: {"foundation": 230, "comprehensive": 234, "extension": 238},
    11: {"foundation": 240, "comprehensive": 245, "extension": 250},
    12: {"foundation": 252, "comprehensive": 257, "extension": 263},
    13: {"foundation": 264, "comprehensive": 268, "extension": 275},
    14: {"foundation": 276, "comprehensive": 283, "extension": 296},
    15: {"foundation": 299, "comprehensive": 305, "extension": 318},
    16: {"foundation": 322, "comprehensive": 324, "extension": 326},
    17: {"foundation": 327, "comprehensive": 330},
    18: {"foundation": 335, "comprehensive": 342, "extension": 349},
    19: {"foundation": 351, "comprehensive": 356, "extension": 366},
    20: {"foundation": 367},
    21: {"foundation": 370, "comprehensive": 372},
    22: {"foundation": 377, "extension": 387},
    23: {"foundation": 390},
}

CHINESE_NUMERALS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
    "十三": 13,
    "十四": 14,
    "十五": 15,
    "十六": 16,
    "十七": 17,
    "十八": 18,
    "十九": 19,
    "二十": 20,
    "二十一": 21,
    "二十二": 22,
    "二十三": 23,
}

QUESTION_MARKER = re.compile(r"^[（(]\s*(\d{1,3})\s*[)）]?")
CHOICE_ANSWER = re.compile(r"[（(]\s*\d+\s*[)）]?\s*([ABCD])\b", re.I)


@dataclass
class Section:
    id: str
    batch: int
    phase: str
    subject: str
    chapter_number: int
    chapter_title: str
    title: str
    question_start: int
    question_next: int | None
    answer_start: int
    answer_next: int | None


@dataclass
class Marker:
    page: int
    y: float
    bottom: float
    question_type: str
    local_number: int

    @property
    def key(self) -> tuple[str, int]:
        return self.question_type, self.local_number


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").replace("畫", "函")


def chapter_number(title: str) -> int:
    match = re.search(r"第([一二三四五六七八九十]+)章", normalize(title))
    if not match or match.group(1) not in CHINESE_NUMERALS:
        raise ValueError(f"无法识别章节序号：{title}")
    return CHINESE_NUMERALS[match.group(1)]


def locate_books() -> tuple[Path, Path, Path]:
    candidates = [
        path
        for path in Path("E:/").glob("*.pdf")
        if "李林880" in path.name
    ]
    answer = max(candidates, key=lambda path: path.stat().st_size)
    workbooks = sorted(
        (path for path in candidates if path != answer),
        key=lambda path: path.stat().st_size,
        reverse=True,
    )
    if len(workbooks) != 2:
        raise FileNotFoundError("未找到李林880高数题册、线代概率题册和解析册")
    return workbooks[0], workbooks[1], answer


def subject_for_heading(title: str) -> str:
    value = normalize(title)
    if "高等数学" in value:
        return "calculus"
    if "线性代数" in value:
        return "linear_algebra"
    if "概率论" in value:
        return "probability"
    raise ValueError(f"未知科目：{title}")


def build_sections(workbooks: Iterable[Path], answer_pages: int) -> list[Section]:
    raw: list[dict[str, Any]] = []
    for workbook in workbooks:
        document = fitz.open(workbook)
        subject = ""
        current_chapter = 0
        current_title = ""
        for level, title, page in document.get_toc():
            value = normalize(title)
            if level == 1:
                subject = subject_for_heading(title)
            elif level == 2:
                current_chapter = chapter_number(title)
                current_title = re.sub(r"^第.+?章", "", value)
            elif level == 3 and value in PHASES:
                phase = PHASES[value]
                if phase == "extension":
                    continue
                raw.append(
                    {
                        "subject": subject,
                        "chapter": current_chapter,
                        "chapter_title": current_title,
                        "phase": phase,
                        "question_start": int(page),
                        "workbook": str(workbook),
                    }
                )
        document.close()

    raw.sort(key=lambda item: (item["chapter"], item["question_start"]))
    answer_order = [
        (chapter, phase, page)
        for chapter, phases in ANSWER_STARTS.items()
        for phase, page in phases.items()
    ]
    answer_order.sort(key=lambda item: item[2])
    answer_next = {
        (chapter, phase): (
            answer_order[index + 1][2] + ANSWER_PAGE_OFFSET
            if index + 1 < len(answer_order)
            else answer_pages
        )
        for index, (chapter, phase, _) in enumerate(answer_order)
    }

    sections: list[Section] = []
    for index, item in enumerate(raw):
        chapter = int(item["chapter"])
        phase = str(item["phase"])
        answer_printed = ANSWER_STARTS.get(chapter, {}).get(phase)
        if answer_printed is None:
            raise ValueError(f"解析册目录缺少：第{chapter}章 {phase}")
        batch = (
            1
            if chapter <= 2
            else 2
            if chapter <= 5
            else 3
            if chapter <= 9
            else 4
            if chapter <= 15
            else 5
        )
        sections.append(
            Section(
                id=f"{SOURCE}-c{chapter:02d}-{phase}",
                batch=batch,
                phase=phase,
                subject=str(item["subject"]),
                chapter_number=chapter,
                chapter_title=str(item["chapter_title"]),
                title=(
                    f"第{chapter}章 {item['chapter_title']} · "
                    f"{PHASE_LABELS[phase]}"
                ),
                question_start=int(item["question_start"]),
                question_next=(
                    int(raw[index + 1]["question_start"])
                    if index + 1 < len(raw)
                    and raw[index + 1]["workbook"] == item["workbook"]
                    else None
                ),
                answer_start=answer_printed + ANSWER_PAGE_OFFSET,
                answer_next=answer_next[(chapter, phase)],
            )
        )
    return sections


def init_schema(conn: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(question_bank_sections)")
    }
    if "source" not in columns:
        conn.execute(
            "ALTER TABLE question_bank_sections "
            "ADD COLUMN source TEXT NOT NULL DEFAULT 'zhangyu1000'"
        )
    if "source_label" not in columns:
        conn.execute(
            "ALTER TABLE question_bank_sections "
            "ADD COLUMN source_label TEXT NOT NULL DEFAULT '张宇1000题'"
        )
    question_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(question_bank)")
    }
    if "source_question_label" not in question_columns:
        conn.execute(
            "ALTER TABLE question_bank "
            "ADD COLUMN source_question_label TEXT NOT NULL DEFAULT ''"
        )
    conn.execute(
        """
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
        )
        """
    )
    conn.commit()


def page_blocks(page: fitz.Page) -> list[tuple[float, float, float, float, str]]:
    return [
        (float(x0), float(y0), float(x1), float(y1), str(text))
        for x0, y0, x1, y1, text, *_ in page.get_text("blocks")
    ]


def heading_type(text: str) -> str | None:
    value = normalize(text)
    if "选择题" in value:
        return "choice"
    if "填空题" in value:
        return "fill"
    if "解答题" in value:
        return "calculation"
    return None


def find_heading_y(page: fitz.Page, label: str) -> tuple[float, float] | None:
    target = PHASES.get(normalize(label))
    matches = [
        (y0, y1)
        for _, y0, _, y1, text in page_blocks(page)
        if phase_from_text(text) == target
    ]
    return matches[-1] if matches else None


def phase_from_text(text: str) -> str | None:
    value = normalize(text)
    if "题" not in value:
        return None
    if "基础" in value:
        return "foundation"
    if "综" in value:
        return "comprehensive"
    if "拓" in value:
        return "extension"
    return None


def answer_ocr_lines(
    document: fitz.Document,
    page_number: int,
    engine: RapidOCR,
) -> list[dict[str, Any]]:
    cache = ASSET_ROOT / "_ocr" / f"page-{page_number:03d}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    scale = 1.5
    pixmap = document[page_number - 1].get_pixmap(
        matrix=fitz.Matrix(scale, scale),
        alpha=False,
    )
    result, _ = engine(pixmap.tobytes("png"))
    lines = []
    for box, text, confidence in result or []:
        lines.append(
            {
                "x": min(point[0] for point in box) / scale,
                "y": min(point[1] for point in box) / scale,
                "bottom": max(point[1] for point in box) / scale,
                "text": str(text).strip(),
                "confidence": float(confidence),
            }
        )
    lines.sort(key=lambda item: (item["y"], item["x"]))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(lines, ensure_ascii=False),
        encoding="utf-8",
    )
    return lines


def answer_section_bounds(
    document: fitz.Document,
    section: Section,
    engine: RapidOCR,
) -> tuple[int, int, float, float]:
    start = section.answer_start
    end = min(section.answer_next or len(document), len(document))
    phase = section.phase
    start_lines = answer_ocr_lines(document, start, engine)
    start_heading = next(
        (
            item
            for item in start_lines
            if phase_from_text(item["text"]) == phase
        ),
        None,
    )
    top = float(start_heading["bottom"] + 1) if start_heading else 38.0

    end_lines = answer_ocr_lines(document, end, engine)
    next_heading = next(
        (
            item
            for item in end_lines
            if phase_from_text(item["text"]) not in (None, phase)
        ),
        None,
    )
    bottom = float(next_heading["y"] - 4) if next_heading else 790.0
    return start, end, top, bottom


def section_bounds(
    document: fitz.Document,
    section: Section,
    *,
    answer: bool,
) -> tuple[int, int, float, float]:
    start = section.answer_start if answer else section.question_start
    following = section.answer_next if answer else section.question_next
    phase_label = PHASE_LABELS[section.phase]
    start_page = document[start - 1]
    start_heading = find_heading_y(start_page, phase_label)
    top = start_heading[1] + 4 if start_heading else 38.0

    if following is None:
        return start, len(document), top, 790.0
    end = min(following, len(document))
    end_page = document[end - 1]
    next_heading = None
    for label in PHASES:
        candidate = find_heading_y(end_page, label)
        if candidate and (next_heading is None or candidate[0] < next_heading[0]):
            next_heading = candidate
    if end == start and start_heading:
        candidates = [
            find_heading_y(end_page, label)
            for label in PHASES
            if label != phase_label
        ]
        candidates = [
            item for item in candidates if item and item[0] > start_heading[0]
        ]
        next_heading = min(candidates, default=None)
    bottom = next_heading[0] - 4 if next_heading else 790.0
    return start, end, top, bottom


def collect_markers(
    document: fitz.Document,
    section: Section,
    *,
    answer: bool,
    engine: RapidOCR | None = None,
) -> list[Marker]:
    if answer:
        if engine is None:
            raise ValueError("解析册题号识别需要 OCR 引擎")
        start, end, start_top, end_bottom = answer_section_bounds(
            document, section, engine
        )
    else:
        start, end, start_top, end_bottom = section_bounds(
            document, section, answer=False
    )
    markers: list[Marker] = []
    current_type: str | None = None
    highest_by_type: dict[str, int] = {}
    for page_number in range(start, end + 1):
        top = start_top if page_number == start else 36.0
        bottom = end_bottom if page_number == end else 790.0
        events: list[tuple[float, str, Any]] = []
        if answer:
            raw_lines = [
                (
                    float(item["x"]),
                    float(item["y"]),
                    0.0,
                    float(item["bottom"]),
                    str(item["text"]),
                )
                for item in answer_ocr_lines(document, page_number, engine)
            ]
        else:
            raw_lines = page_blocks(document[page_number - 1])
        for x0, y0, _, y1, text in raw_lines:
            if y0 < top or y0 >= bottom or y0 > 775:
                continue
            question_type = heading_type(text)
            if question_type:
                events.append((y0, "type", question_type))
            match = QUESTION_MARKER.match(text.strip())
            if match and x0 < 115:
                events.append(
                    (
                        y0,
                        "question",
                        (int(match.group(1)), y1),
                    )
                )
        for y, kind, value in sorted(events, key=lambda item: item[0]):
            if kind == "type":
                current_type = str(value)
            elif current_type:
                local_number, bottom_y = value
                if local_number <= highest_by_type.get(current_type, 0):
                    continue
                markers.append(
                    Marker(
                        page=page_number,
                        y=y,
                        bottom=float(bottom_y),
                        question_type=current_type,
                        local_number=int(local_number),
                    )
                )
                highest_by_type[current_type] = int(local_number)
    return markers


def crop_asset_path(
    section: Section,
    kind: str,
    sequence: int,
    part: int,
) -> Path:
    directory = ASSET_ROOT / section.id / kind
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"q{sequence:03d}-{part:02d}.webp"


def save_page_clip(
    page: fitz.Page,
    rect: fitz.Rect,
    path: Path,
    scale: float = 2.2,
) -> str:
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(scale, scale),
        clip=rect,
        alpha=False,
    )
    image = Image.open(__import__("io").BytesIO(pixmap.tobytes("png")))
    gray = image.convert("L")
    ink = gray.point(lambda value: 255 if value < 245 else 0)
    bounds = ink.getbbox()
    if bounds:
        margin = 18
        top = max(0, bounds[1] - margin)
        bottom = min(image.height, bounds[3] + margin)
        image = image.crop((0, top, image.width, bottom))
    image.save(path, "WEBP", quality=90, method=6)
    return path.relative_to(ROOT).as_posix()


def text_in_rect(page: fitz.Page, rect: fitz.Rect) -> str:
    values = [
        text.strip()
        for x0, y0, x1, y1, text in page_blocks(page)
        if fitz.Rect(x0, y0, x1, y1).intersects(rect) and text.strip()
    ]
    return "\n".join(values)


def extract_records(
    document: fitz.Document,
    section: Section,
    *,
    answer: bool,
    engine: RapidOCR | None = None,
    expected_keys: Iterable[tuple[str, int]] | None = None,
) -> dict[tuple[str, int], dict[str, Any]]:
    markers = collect_markers(
        document,
        section,
        answer=answer,
        engine=engine,
    )
    if not answer:
        markers = seed_unnumbered_question_types(
            document,
            section,
            markers,
        )
    if not markers:
        if not answer:
            return {}
    if answer and expected_keys:
        markers = seed_missing_answer_types(
            document,
            section,
            engine,
            markers,
            list(expected_keys),
        )
        markers = synthesize_missing_markers(
            markers,
            list(expected_keys),
            document[0].rect.height,
        )
    if answer:
        if engine is None:
            raise ValueError("解析册提取需要 OCR 引擎")
        start, end, _, end_bottom = answer_section_bounds(
            document, section, engine
        )
    else:
        start, end, _, end_bottom = section_bounds(
            document, section, answer=False
        )
    records: dict[tuple[str, int], dict[str, Any]] = {}
    for index, marker in enumerate(markers):
        next_marker = markers[index + 1] if index + 1 < len(markers) else None
        record = {
            "images": [],
            "pages": [],
            "text": [],
            "marker": marker,
        }
        last_page = next_marker.page if next_marker else end
        for page_number in range(marker.page, last_page + 1):
            page = document[page_number - 1]
            top = marker.y - 3 if page_number == marker.page else 38.0
            if next_marker and page_number == next_marker.page:
                bottom = next_marker.y - 4
            elif page_number == end:
                bottom = end_bottom
            else:
                bottom = 775.0
            if bottom <= top + 8:
                continue
            rect = fitz.Rect(52.0, top, 548.0, bottom)
            path = crop_asset_path(
                section,
                "answers" if answer else "questions",
                index + 1,
                len(record["images"]) + 1,
            )
            record["images"].append(save_page_clip(page, rect, path))
            record["pages"].append(page_number)
            record["text"].append(text_in_rect(page, rect))
        records[marker.key] = record
    return records


def seed_unnumbered_question_types(
    document: fitz.Document,
    section: Section,
    markers: list[Marker],
) -> list[Marker]:
    present_types = {marker.question_type for marker in markers}
    start, end, top, bottom = section_bounds(
        document, section, answer=False
    )
    for page_number in range(start, end + 1):
        page_top = top if page_number == start else 36.0
        page_bottom = bottom if page_number == end else 790.0
        blocks = [
            block
            for block in page_blocks(document[page_number - 1])
            if page_top <= block[1] < page_bottom and block[1] < 775
        ]
        for index, block in enumerate(blocks):
            question_type = heading_type(block[4])
            if not question_type or question_type in present_types:
                continue
            following = next(
                (
                    candidate
                    for candidate in blocks[index + 1 :]
                    if candidate[1] > block[1] + 3
                    and heading_type(candidate[4]) is None
                ),
                None,
            )
            if following:
                markers.append(
                    Marker(
                        page=page_number,
                        y=following[1],
                        bottom=following[3],
                        question_type=question_type,
                        local_number=1,
                    )
                )
                present_types.add(question_type)
    return sorted(markers, key=lambda marker: (marker.page, marker.y))


def seed_missing_answer_types(
    document: fitz.Document,
    section: Section,
    engine: RapidOCR | None,
    markers: list[Marker],
    expected_keys: list[tuple[str, int]],
) -> list[Marker]:
    if engine is None:
        return markers
    present_types = {marker.question_type for marker in markers}
    expected_by_type = {
        question_type: sorted(
            number
            for kind, number in expected_keys
            if kind == question_type
        )
        for question_type in TYPE_LABELS
    }
    start, end, top, bottom = answer_section_bounds(document, section, engine)
    for question_type, numbers in expected_by_type.items():
        if not numbers or question_type in present_types:
            continue
        for page_number in range(start, end + 1):
            page_top = top if page_number == start else 36.0
            page_bottom = bottom if page_number == end else 790.0
            heading = next(
                (
                    item
                    for item in answer_ocr_lines(
                        document, page_number, engine
                    )
                    if page_top <= float(item["y"]) < page_bottom
                    and heading_type(str(item["text"])) == question_type
                ),
                None,
            )
            if heading:
                markers.append(
                    Marker(
                        page=page_number,
                        y=float(heading["bottom"]) + 3,
                        bottom=float(heading["bottom"]) + 17,
                        question_type=question_type,
                        local_number=numbers[0],
                    )
                )
                break
    return sorted(markers, key=lambda marker: (marker.page, marker.y))


def synthesize_missing_markers(
    markers: list[Marker],
    expected_keys: list[tuple[str, int]],
    page_height: float,
) -> list[Marker]:
    expected_set = set(expected_keys)
    markers = [marker for marker in markers if marker.key in expected_set]
    known = {marker.key: marker for marker in markers}
    for question_type in TYPE_LABELS:
        expected = sorted(
            number
            for kind, number in expected_keys
            if kind == question_type
        )
        present = sorted(
            (
                marker
                for marker in markers
                if marker.question_type == question_type
            ),
            key=lambda marker: marker.local_number,
        )
        if not expected or not present:
            continue

        def position(marker: Marker) -> float:
            return (marker.page - 1) * page_height + marker.y

        gaps = []
        for left, right in zip(present, present[1:]):
            number_gap = right.local_number - left.local_number
            if number_gap > 0:
                gaps.append((position(right) - position(left)) / number_gap)
        typical_gap = (
            sorted(gaps)[len(gaps) // 2]
            if gaps
            else 72.0
        )
        for number in expected:
            key = (question_type, number)
            if key in known:
                continue
            previous = max(
                (
                    marker
                    for marker in present
                    if marker.local_number < number
                ),
                default=None,
                key=lambda marker: marker.local_number,
            )
            following = min(
                (
                    marker
                    for marker in present
                    if marker.local_number > number
                ),
                default=None,
                key=lambda marker: marker.local_number,
            )
            if previous and following:
                fraction = (
                    (number - previous.local_number)
                    / (following.local_number - previous.local_number)
                )
                absolute = position(previous) + (
                    position(following) - position(previous)
                ) * fraction
            elif previous:
                absolute = position(previous) + typical_gap * (
                    number - previous.local_number
                )
            else:
                absolute = position(following) - typical_gap * (
                    following.local_number - number
                )
            page, y = divmod(max(0.0, absolute), page_height)
            synthetic = Marker(
                page=int(page) + 1,
                y=y,
                bottom=y + 14,
                question_type=question_type,
                local_number=number,
            )
            markers.append(synthetic)
            present.append(synthetic)
            present.sort(key=lambda marker: marker.local_number)
            known[key] = synthetic
    return sorted(markers, key=lambda marker: (marker.page, marker.y))


def recognize_choice_answer(
    document: fitz.Document,
    marker: Marker,
    engine: RapidOCR,
) -> tuple[str | None, float]:
    for item in answer_ocr_lines(document, marker.page, engine):
        if abs(float(item["y"]) - marker.y) > 5:
            continue
        match = CHOICE_ANSWER.search(str(item["text"]))
        if match:
            return match.group(1).upper(), float(item["confidence"])
    page = document[marker.page - 1]
    rect = fitz.Rect(60.0, max(0.0, marker.y - 5), 175.0, marker.bottom + 12)
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(4.0, 4.0),
        clip=rect,
        alpha=False,
    )
    result, _ = engine(pixmap.tobytes("png"))
    for _, text, confidence in result or []:
        match = CHOICE_ANSWER.search(str(text))
        if match:
            return match.group(1).upper(), float(confidence)
    return None, 0.0


def insert_section(
    conn: sqlite3.Connection,
    question_document: fitz.Document,
    answer_document: fitz.Document,
    section: Section,
    engine: RapidOCR,
) -> dict[str, int]:
    print(f"[批次 {section.batch}] {section.title}")
    section_dir = ASSET_ROOT / section.id
    if section_dir.exists():
        shutil.rmtree(section_dir)
    question_records = extract_records(
        question_document, section, answer=False
    )
    answer_records = extract_records(
        answer_document,
        section,
        answer=True,
        engine=engine,
        expected_keys=question_records,
    )

    conn.execute(
        """
        INSERT INTO question_bank_sections(
            id, batch, phase, subject, chapter_number, title,
            question_page_start, question_page_end,
            answer_page_start, answer_page_end, source, source_label
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            source=excluded.source,
            source_label=excluded.source_label,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            section.id,
            section.batch,
            section.phase,
            section.subject,
            section.chapter_number,
            section.title,
            section.question_start,
            section.question_next or len(question_document),
            section.answer_start,
            section.answer_next or len(answer_document),
            SOURCE,
            SOURCE_LABEL,
        ),
    )
    conn.execute("DELETE FROM question_bank WHERE section_id = ?", (section.id,))

    matched = 0
    auto_gradable = 0
    for sequence, (key, question) in enumerate(question_records.items(), start=1):
        answer = answer_records.get(key)
        answer_choice = None
        confidence = 0.0
        if answer:
            matched += 1
            if key[0] == "choice":
                answer_choice, confidence = recognize_choice_answer(
                    answer_document,
                    answer["marker"],
                    engine,
                )
        gradable = bool(answer_choice)
        auto_gradable += int(gradable)
        source_label = f"{TYPE_LABELS[key[0]]} {key[1]}"
        question_text = "\n".join(question["text"])
        if "证明" in question_text or "求证" in question_text:
            question_type = "proof"
        else:
            question_type = key[0]
        conn.execute(
            """
            INSERT INTO question_bank(
                id, section_id, question_number, question_type,
                question_text, question_images_json, answer_text,
                answer_choice, answer_images_json, auto_gradable,
                confidence, review_status, source_question_pages,
                source_answer_pages, source_question_label
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{section.id}-q{sequence:03d}",
                section.id,
                sequence,
                question_type,
                question_text,
                json.dumps(question["images"], ensure_ascii=False),
                answer_choice or "",
                answer_choice,
                json.dumps(
                    answer["images"] if answer else [],
                    ensure_ascii=False,
                ),
                int(gradable),
                confidence,
                "verified" if gradable and confidence >= 0.68 else "needs_review",
                ",".join(map(str, question["pages"])),
                ",".join(map(str, answer["pages"])) if answer else "",
                source_label,
            ),
        )

    count = len(question_records)
    conn.execute(
        """
        UPDATE question_bank_sections
        SET question_count = ?, verified_count = ?, updated_at=CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (count, auto_gradable, section.id),
    )
    conn.commit()
    return {
        "questions": count,
        "matched_answers": matched,
        "auto_gradable": auto_gradable,
        "needs_review": count - auto_gradable,
        "asset_files": (
            len(list(section_dir.rglob("*.webp")))
            if section_dir.exists()
            else 0
        ),
    }


def validate_batch(conn: sqlite3.Connection, batch: int) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT s.id, s.title, s.question_count,
               COUNT(q.id) AS stored,
               SUM(CASE WHEN q.answer_images_json != '[]' THEN 1 ELSE 0 END)
                   AS with_answer,
               SUM(q.auto_gradable) AS auto_gradable
        FROM question_bank_sections s
        LEFT JOIN question_bank q ON q.section_id = s.id
        WHERE s.source = ? AND s.batch = ?
        GROUP BY s.id
        ORDER BY s.chapter_number, s.phase
        """,
        (SOURCE, batch),
    ).fetchall()
    sections = [dict(row) for row in rows]
    problems = [
        row
        for row in sections
        if int(row["question_count"]) != int(row["stored"])
        or int(row["stored"]) == 0
        or int(row["with_answer"] or 0) < int(row["stored"]) * 0.85
    ]
    missing_answers = conn.execute(
        """
        SELECT s.id AS section_id, s.title, q.id AS question_id,
               q.source_question_label
        FROM question_bank q
        JOIN question_bank_sections s ON s.id = q.section_id
        WHERE s.source = ? AND s.batch = ?
          AND q.answer_images_json = '[]'
        ORDER BY s.chapter_number, s.phase, q.question_number
        """,
        (SOURCE, batch),
    ).fetchall()
    return {
        "batch": batch,
        "sections": len(sections),
        "questions": sum(int(row["stored"]) for row in sections),
        "with_answer": sum(int(row["with_answer"] or 0) for row in sections),
        "auto_gradable": sum(
            int(row["auto_gradable"] or 0) for row in sections
        ),
        "problems": problems,
        "missing_answers": [dict(row) for row in missing_answers],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, choices=(1, 2, 3, 4, 5))
    parser.add_argument("--section")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--reset-source", action="store_true")
    args = parser.parse_args()

    calculus_book, other_book, answer_book = locate_books()
    answer_document = fitz.open(answer_book)
    sections = build_sections(
        (calculus_book, other_book),
        len(answer_document),
    )
    if args.list:
        for section in sections:
            print(section)
        answer_document.close()
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    if args.reset_source:
        conn.execute(
            "DELETE FROM question_bank WHERE section_id IN "
            "(SELECT id FROM question_bank_sections WHERE source = ?)",
            (SOURCE,),
        )
        conn.execute(
            "DELETE FROM question_bank_sections WHERE source = ?",
            (SOURCE,),
        )
        conn.commit()
        if ASSET_ROOT.exists():
            shutil.rmtree(ASSET_ROOT)

    if args.validate:
        batches = [args.batch] if args.batch else range(1, 6)
        print(
            json.dumps(
                [validate_batch(conn, batch) for batch in batches],
                ensure_ascii=False,
                indent=2,
            )
        )
        conn.close()
        answer_document.close()
        return

    selected = [
        section
        for section in sections
        if (args.batch is None or section.batch == args.batch)
        and (args.section is None or section.id == args.section)
    ]
    if args.section and not selected:
        raise ValueError(f"未知章节：{args.section}")

    engine = RapidOCR()
    documents = {
        "calculus": fitz.open(calculus_book),
        "linear_algebra": fitz.open(other_book),
        "probability": fitz.open(other_book),
    }
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
            report = insert_section(
                conn,
                documents[section.subject],
                answer_document,
                section,
                engine,
            )
            reports[section.id] = report
            totals["sections"] += 1
            for key in (
                "questions",
                "matched_answers",
                "auto_gradable",
                "needs_review",
            ):
                totals[key] += int(report[key])
        batch_values = sorted({section.batch for section in selected})
        validation = [
            validate_batch(conn, batch)
            for batch in batch_values
        ]
        report_path = ASSET_ROOT / (
            f"batch-{args.batch}-report.json"
            if args.batch
            else "full-report.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "totals": totals,
                    "sections": reports,
                    "validation": validation,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {"totals": totals, "validation": validation},
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        for document in documents.values():
            document.close()
        answer_document.close()
        conn.close()


if __name__ == "__main__":
    main()
