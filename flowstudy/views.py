from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import re
import time
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from flowstudy.ai_tutor import (
    conversation_summary,
    opening_turn,
    tutor_stream,
    tutor_turn,
)
from flowstudy.content import (
    get_concept,
    get_question,
    get_topic,
    get_topic_tree,
)
from flowstudy.config import (
    BASE_DIR,
    LULU_CORRECT_IMAGE,
    LULU_FAVORITES_SCENE,
    LULU_FINISH_VIDEO,
    LULU_HOME_SCENE,
    LULU_INCORRECT_IMAGE,
    LULU_LEARNING_SCENE,
    LULU_TUTOR_IMAGE,
    LULU_WRONG_SCENE,
    USER_AVATAR_IMAGE,
    static_asset_url,
)
from flowstudy.database import (
    add_tutor_message,
    finalize_ai_tutor_attempts,
    finish_tutor_session,
    choose_question_bank_questions,
    choose_daily_question,
    delete_wrong_question,
    get_question_knowledge,
    get_ai_tutor_attempts,
    get_concept_learning_context,
    get_concept_mastery,
    get_growth_overview,
    get_question_bank_overview,
    get_question_bank_sections,
    get_summaries,
    get_summary,
    get_tutor_messages,
    get_tutor_session,
    get_weak_concepts,
    get_wrong_questions,
    record_activity,
    record_ai_tutor_attempt,
    record_attempt,
    record_question_bank_attempt,
    start_daily_session,
    update_daily_session,
    resolve_wrong_question,
    save_favorite_reflection,
    save_question_dialogue_summary,
    set_summary_favorite,
    start_tutor_session,
    update_concept_mastery,
    update_tutor_context,
)
from flowstudy.chat_agent import chat_turn, start_chat
from flowstudy.agent_trace import trace_to_progress
from flowstudy.media import render_cropped_video
from flowstudy.react_agent import (
    close_diagnosis,
    diagnose_turn,
    start_diagnosis,
)
from services.ai_service import AIServiceError, AITutor


IDLE_TIMEOUT_SECONDS = 300
LULU_CHAT_TIMEOUT_SECONDS = 150
_LULU_CHAT_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lulu-chat")


def sync_study_timer(page: str) -> None:
    if page == "learning":
        return
    last = st.session_state.pop("_activity_at", None)
    topic_id = st.session_state.pop("_activity_topic", None)
    if last and topic_id:
        record_activity(topic_id, min(int(time.time() - last), IDLE_TIMEOUT_SECONDS))
    st.session_state["learning_mode"] = "tree"
    st.session_state.pop("completed_summary_id", None)


def _touch_activity(topic_id: str) -> bool:
    now = time.time()
    previous = st.session_state.get("_activity_at")
    previous_topic = st.session_state.get("_activity_topic")
    was_paused = False
    if previous and previous_topic:
        elapsed = max(0, int(now - float(previous)))
        record_activity(previous_topic, min(elapsed, IDLE_TIMEOUT_SECONDS))
        was_paused = elapsed > IDLE_TIMEOUT_SECONDS
    st.session_state["_activity_at"] = now
    st.session_state["_activity_topic"] = topic_id
    return was_paused


def _go_learning(concept_key: str | None = None) -> None:
    st.session_state["app_view"] = "learning"
    st.query_params["page"] = "learning"
    st.session_state["learning_mode"] = "bank" if concept_key else "tree"
    st.session_state.pop("completed_summary_id", None)
    st.session_state.pop("growth_reward", None)
    if concept_key:
        st.session_state["requested_section_id"] = concept_key


def _go_daily() -> None:
    st.session_state["app_view"] = "daily"
    st.query_params["page"] = "daily"
    st.session_state.pop("daily_session", None)


def _go_lulu_chat() -> None:
    st.session_state["app_view"] = "lulu_chat"
    st.query_params["page"] = "lulu_chat"
    if "lulu_chat" not in st.session_state:
        st.session_state["lulu_chat"] = start_chat()


def _resume_learning(session_id: int) -> None:
    st.session_state["app_view"] = "learning"
    st.query_params["page"] = "learning"
    st.session_state["active_tutor_session_id"] = session_id
    st.session_state["learning_mode"] = "tutor"
    st.session_state.pop("completed_summary_id", None)


def _go_home() -> None:
    st.session_state["app_view"] = "home"
    st.query_params["page"] = "home"


def _go_reefs() -> None:
    st.session_state["app_view"] = "reefs"
    st.query_params["page"] = "reefs"


def _go_treasures() -> None:
    st.session_state["app_view"] = "treasures"
    st.query_params["page"] = "treasures"


def _go_page(page: str) -> None:
    if page != "lulu_chat":
        _discard_lulu_chat()
    st.session_state["app_view"] = page
    if page == "learning":
        st.session_state["learning_mode"] = "tree"
        st.session_state.pop("bank_session", None)
        st.session_state.pop("requested_section_id", None)
    st.query_params["page"] = page


def _discard_lulu_chat() -> None:
    pending = st.session_state.pop("lulu_chat_pending", None)
    future = pending.get("future") if isinstance(pending, dict) else None
    if future is not None and hasattr(future, "cancel"):
        future.cancel()
    st.session_state.pop("lulu_chat", None)
    st.session_state.pop("lulu_open_question", None)


def _question_image_path(value: object) -> Path | None:
    """Resolve a bank image without allowing an arbitrary filesystem path."""
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = (BASE_DIR / value.strip()).resolve()
    try:
        candidate.relative_to(BASE_DIR.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


@st.cache_data(show_spinner=False)
def _load_question_image(path: str, modified_ns: int) -> bytes:
    """Cache the bytes so reopening a question does not rebuild its media."""
    return Path(path).read_bytes()


def _render_back_arrow(parent_page: str, key: str) -> None:
    """Render the small parent-menu control shared by content pages."""
    with st.container(key=f"page_back_{key}"):
        st.button(
            "←",
            key=f"page_back_button_{key}",
            width="content",
            on_click=_go_page,
            args=(parent_page,),
        )


def _page_link(
    label: str,
    page: str,
    *,
    primary: bool = False,
    circle: bool = False,
) -> None:
    def navigate() -> None:
        # Keep navigation inside the current Streamlit session. A normal href
        # reloads the whole document and needlessly recreates every component.
        _go_page(page)

    st.button(
        label,
        key=f"page_link_{page}_{'circle' if circle else 'bar'}",
        type="primary" if primary else "secondary",
        width="content" if circle else "stretch",
        on_click=navigate,
    )


def _render_ocean_hero(
    key: str,
    image: Any,
    eyebrow: str,
    title: str,
    subtitle: str,
) -> Any:
    image_uri = static_asset_url(image)
    st.markdown(
        f"""
        <style>
        .st-key-ocean_hero_{key} {{
            background-image:
                linear-gradient(90deg, rgba(255,253,246,.98) 0%, rgba(255,253,246,.91) 37%,
                rgba(255,253,246,.22) 64%, rgba(255,253,246,.02) 100%),
                url("{image_uri}");
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key=f"ocean_hero_{key}"):
        copy, _ = st.columns([1.08, 1])
        with copy:
            st.markdown(
                f"""
                <div class="ocean-hero-copy">
                    <div class="ocean-kicker">{escape(eyebrow)}</div>
                    <h1>{escape(title)}</h1>
                    <p>{escape(subtitle)}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
    return copy


def _voyager_rank(mastery: float) -> tuple[str, str]:
    if mastery < 0.4:
        return "🌱", "萌芽航海员"
    if mastery < 0.6:
        return "🌿", "见习探索者"
    if mastery < 0.8:
        return "⛵", "熟练航海家"
    if mastery < 1.0:
        return "🌊", "深海探索者"
    return "⭐", "传奇发现者"


def _render_growth_tree(show_title: bool = True) -> None:
    overview = get_question_bank_overview()
    overall = (
        overview["explored"] / overview["sections"]
        if overview["sections"]
        else 0.0
    )
    emoji, rank = _voyager_rank(overall)
    if show_title:
        st.markdown("## 你的探索者航程")
    st.markdown(
        f"""
        <div class="warm-card growth-card">
            <div class="warm-card-label">当前航海身份</div>
            <div class="voyager-rank">{emoji} {rank}</div>
            <div class="warm-card-copy">每完成一章探索，知识海图就会亮起一片新的海域。</div>
            <div class="warm-card-title">已探索章节：{overview['explored']} / {overview['sections']}</div>
            <div style="height:12px;background:rgba(255,255,255,.75);border-radius:99px;overflow:hidden;">
                <div style="width:{overall:.1%};height:100%;background:#69b7c9;border-radius:99px;"></div>
            </div>
            <div class="level-grid">
                <div class="level-pill">🌱 萌芽航海员</div>
                <div class="level-pill">🌿 见习探索者</div>
                <div class="level-pill">⛵ 熟练航海家</div>
                <div class="level-pill">🌊 深海探索者</div>
                <div class="level-pill">⭐ 传奇发现者</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_welcome() -> None:
    """Minimal first screen: the pet and the two real starting points."""
    st.markdown(
        """
        <div class="welcome-page">
            <div class="welcome-copy">
                <h1>和噜噜一起学习</h1>
                <p>今天想聊聊，还是开始刷题？</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    with left:
        _page_link("和噜噜聊聊", "lulu_chat", circle=True)
    with right:
        _page_link("开始刷题", "home", primary=True, circle=True)


def render_home() -> None:
    _render_back_arrow("welcome", "home")
    st.markdown(
        '<div class="home-background-boost"></div>',
        unsafe_allow_html=True,
    )
    _render_growth_tree(show_title=False)

    with st.container(border=True):
        st.markdown("### 每日一题")
        st.caption(
            "从错题或掌握较弱的章节中抽取一道题。答错后，噜噜会启动有限的知识补全流程。"
        )
        _page_link("开始每日一题", "daily", primary=True)

    explore_copy = _render_ocean_hero(
        "home",
        LULU_HOME_SCENE,
        "知识探索准备中",
        "今天准备探索哪片知识海域？",
        "打开完整知识海图，看看每座岛屿的掌握情况，再选择今天想探索的地方。",
    )
    with explore_copy:
        _page_link("开始探索", "learning", primary=True)

    reef_copy = _render_ocean_hero(
        "home_reefs",
        LULU_WRONG_SCENE,
        "触礁记录",
        "遇到暗礁，不代表走错了海域",
        "回看曾经卡住的题目，先重新作答，再把真正的原因弄明白。",
    )
    with reef_copy:
        _page_link("查看触礁记录", "reefs", primary=True)

    treasure_copy = _render_ocean_hero(
        "home_treasures",
        LULU_FAVORITES_SCENE,
        "发现宝藏",
        "把闪光的想法装进宝箱",
        "学习总结、顿悟和重要反思都收藏在这里，需要时再回来看看。",
    )
    with treasure_copy:
        _page_link("打开宝箱", "treasures", primary=True)


def _format_elapsed(seconds: float) -> str:
    """Format the live agent duration without exposing internal reasoning."""
    elapsed = max(0, int(seconds))
    minutes, remainder = divmod(elapsed, 60)
    if minutes:
        return f"{minutes}分{remainder:02d}秒"
    return f"{remainder}秒"


@st.fragment(run_every="500ms")
def _poll_lulu_chat() -> None:
    job = st.session_state.get("lulu_chat_pending")
    if job is None:
        return
    future = job["future"]
    if not future.done():
        with st.chat_message("assistant", avatar=str(LULU_TUTOR_IMAGE)):
            stages: list[str] = []
            for event in job.get("trace_events", []):
                label = trace_to_progress(event)
                if not stages or stages[-1] != label:
                    stages.append(label)
            if not stages:
                stages = list(job.get("stages", []))
            stages = stages[-6:]
            current_stage = stages[-1] if stages else job.get("stage", "噜噜正在思考")
            elapsed = _format_elapsed(
                time.monotonic() - float(job.get("started_at", time.monotonic()))
            )
            st.markdown(f"⌛ {current_stage}（已思考 {elapsed}）…")
            for stage in stages[:-1]:
                st.caption(f"✓ {stage}")
        if time.monotonic() - float(job.get("started_at", time.monotonic())) > LULU_CHAT_TIMEOUT_SECONDS:
            future.cancel()
            st.session_state.pop("lulu_chat_pending", None)
            chat_state = st.session_state.get("lulu_chat", {})
            chat_state["messages"] = [
                item for item in chat_state.get("messages", []) if not item.get("pending")
            ]
            st.session_state["lulu_chat"] = chat_state
            st.session_state["lulu_chat_error"] = "噜噜这次响应超时了，请稍后重新发送。"
            st.rerun()
        return
    st.session_state.pop("lulu_chat_pending", None)
    try:
        st.session_state["lulu_chat"] = future.result()
    except Exception as exc:
        chat_state = st.session_state.get("lulu_chat", {})
        chat_state["messages"] = [
            item for item in chat_state.get("messages", []) if not item.get("pending")
        ]
        st.session_state["lulu_chat"] = chat_state
        st.session_state["lulu_chat_error"] = f"噜噜这次没有完成请求：{exc}"
        st.rerun()
        return
    st.rerun()


def _run_lulu_chat(
    job: dict[str, Any], state: dict[str, Any], user_message: str
) -> dict[str, Any]:
    def update_progress(stage: str) -> None:
        job["stage"] = stage
        stages = job.setdefault("stages", [])
        if not stages or stages[-1] != stage:
            stages.append(stage)

    def update_trace(event: dict[str, Any]) -> None:
        job.setdefault("trace_events", []).append(event)
        update_progress(trace_to_progress(event))

    return chat_turn(
        state,
        user_message,
        append_user=False,
        progress_callback=update_progress,
        trace_callback=update_trace,
    )


def render_lulu_chat() -> None:
    _render_back_arrow("welcome", "chat")
    st.markdown('<div class="lulu-chat-page"></div>', unsafe_allow_html=True)
    state = st.session_state.get("lulu_chat")
    if state is None:
        state = start_chat()
        st.session_state["lulu_chat"] = state

    # Process the submitted message before drawing the history. Streamlit already
    # reruns the page for chat_input, so a second full rerun only delays the
    # user's bubble and the thinking indicator.
    message = st.chat_input(
        "输入消息，按回车发送",
        disabled=st.session_state.get("lulu_chat_pending") is not None,
    )
    if message is not None:
        if not message.strip():
            st.warning("先写下你想问噜噜的内容。")
        else:
            user_message = message.strip()
            user_entry = {"role": "user", "content": user_message}
            progress_entry = {
                "role": "assistant",
                "content": "⌛ 噜噜正在思考，请稍候…",
                "pending": True,
            }
            previous_messages = list(state.get("messages", []))
            state = {
                **state,
                "messages": previous_messages + [user_entry, progress_entry],
            }
            st.session_state["lulu_chat"] = state
            worker_state = {
                **state,
                "messages": previous_messages + [user_entry],
            }
            job = {
                "started_at": time.monotonic(),
                "stage": "正在理解你的请求",
                "stages": ["正在理解你的请求"],
                "trace_events": [],
            }
            job["future"] = _LULU_CHAT_EXECUTOR.submit(
                _run_lulu_chat,
                job,
                worker_state,
                user_message,
            )
            st.session_state["lulu_chat_pending"] = job

    chat_error = st.session_state.pop("lulu_chat_error", None)
    if chat_error:
        st.error(chat_error)

    for message_index, message in enumerate(state.get("messages", [])):
        if message.get("pending"):
            continue
        role = message.get("role", "assistant")
        avatar = str(USER_AVATAR_IMAGE) if role == "user" else str(LULU_TUTOR_IMAGE)
        with st.chat_message(role, avatar=avatar):
            st.markdown(_chat_markdown(message.get("content", "")))
            question = message.get("question")
            if isinstance(question, dict):
                # Use the same image list as the刷题页. Do not rebuild it from
                # crops or generate a second composite image here.
                image_paths = question.get("question_images") or []
                valid_image_paths = [
                    image_path
                    for image_path in (_question_image_path(path) for path in image_paths)
                    if image_path is not None
                ]
                rendered_image = bool(valid_image_paths)
                question_key = f"lulu-question-{message_index}"
                opened_question = st.session_state.get("lulu_open_question")
                if valid_image_paths:
                    if st.button(
                        "收起完整原题"
                        if opened_question == question_key
                        else "点击查看完整原题",
                        key=question_key,
                        use_container_width=False,
                    ):
                        st.session_state["lulu_open_question"] = (
                            None if opened_question == question_key else question_key
                        )
                        st.rerun()
                    if opened_question == question_key:
                        # Keep one viewer control while showing the same source
                        # images that the刷题页 uses, in their stored order.
                        with st.container(
                            key=f"lulu_question_viewer_{message_index}",
                            border=True,
                        ):
                            for image_path in valid_image_paths:
                                try:
                                    image_bytes = _load_question_image(
                                        str(image_path), image_path.stat().st_mtime_ns
                                    )
                                except OSError:
                                    st.error("原题图片暂时无法读取，请收起后重试。")
                                else:
                                    st.image(image_bytes, width="stretch")
                if not rendered_image and question.get("question_text"):
                    st.markdown(_chat_markdown(question["question_text"]))
            for answer_path in message.get("answer_images", []) or []:
                image_path = _question_image_path(answer_path)
                if image_path is not None:
                    try:
                        st.image(
                            _load_question_image(
                                str(image_path), image_path.stat().st_mtime_ns
                            ),
                            width="stretch",
                        )
                    except OSError:
                        st.warning("固定解析图片暂时无法读取，请稍后重试。")
    _poll_lulu_chat()

def _new_tutor_session(concept_key: str | None = None) -> int:
    if concept_key:
        focus = get_concept_learning_context(concept_key)
    else:
        weak = get_weak_concepts(1)
        if not weak:
            raise RuntimeError("固定知识树中没有可用 Concept")
        focus = weak[0]
    favorites = [row["insight"] for row in get_summaries(3, favorites_only=True)]
    opening = opening_turn(focus, favorites)
    session_id = start_tutor_session(focus["concept_id"])
    st.session_state["active_tutor_session_id"] = session_id
    add_tutor_message(
        session_id,
        "assistant",
        opening["reply"],
        focus["concept_id"],
    )
    mastery_row = get_concept_mastery().get(focus["concept_id"])
    initial_mastery = (
        float(mastery_row["mastery"])
        if mastery_row and int(mastery_row["attempts"]) > 0
        else 0.0
    )
    update_tutor_context(
        session_id,
        {
            "current_question": opening["question"],
            "asked_ids": [opening["question"]["id"]],
            "assessments": [],
            "attempt_records": [],
            "initial_mastery": initial_mastery,
        },
    )
    return session_id


def _active_or_new_session(concept_key: str | None = None) -> Any:
    if concept_key:
        return get_tutor_session(_new_tutor_session(concept_key))
    session_id = st.session_state.get("active_tutor_session_id")
    session = get_tutor_session(int(session_id)) if session_id else None
    if session and session["status"] == "active":
        return session
    return get_tutor_session(_new_tutor_session())


def _message_dicts(rows: list[Any]) -> list[dict[str, str]]:
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def _process_tutor_answer(session: Any, answer: str) -> bool:
    context = json.loads(session["context_json"] or "{}")
    question = context["current_question"]
    asked_ids = list(context.get("asked_ids", []))
    assessments = list(context.get("assessments", []))
    attempt_records = list(context.get("attempt_records", []))
    concept_key = session["focus_concept_id"]

    history_rows = get_tutor_messages(session["id"])
    result = tutor_turn(
        concept_key,
        question,
        answer,
        asked_ids,
        [
            *_message_dicts(history_rows),
            {"role": "user", "content": answer},
        ],
    )
    add_tutor_message(session["id"], "user", answer, concept_key)
    assessment = result["assessment"]
    update_concept_mastery(concept_key, assessment)
    concept = get_concept(concept_key)
    question_snapshot = {
        **question,
        "knowledge_point": concept["concept"],
        "concept_id": concept_key,
        "last_user_answer": answer,
        "mistake_type": result["mistake_type"],
        "source": "openrouter_deepseek",
    }
    is_correct = assessment == "correct"
    record_attempt(
        question_snapshot,
        concept["topic_id"],
        [],
        is_correct,
        "tutor",
        update_mastery=False,
    )
    record_ai_tutor_attempt(
        int(session["id"]),
        concept["topic_id"],
        concept_key,
        question_snapshot,
        answer,
        is_correct,
        result["mistake_type"],
    )
    attempt_records.append(
        {
            "question": question["question"],
            "user_answer": answer,
            "is_correct": is_correct,
            "mistake_type": result["mistake_type"],
        }
    )
    add_tutor_message(
        session["id"],
        "assistant",
        result["reply"],
        concept_key,
        assessment,
    )
    assessments.append(assessment)
    if result["question"]:
        asked_ids.append(result["question"]["id"])
    update_tutor_context(
        session["id"],
        {
            **context,
            "current_question": result["question"],
            "asked_ids": asked_ids,
            "assessments": assessments,
            "attempt_records": attempt_records,
            "complete": bool(result["complete"]),
        },
    )
    return bool(result["complete"])


def _complete_session(session: Any) -> tuple[int, dict[str, Any]]:
    context = json.loads(session["context_json"] or "{}")
    rows = get_tutor_messages(session["id"])
    assessments = list(context.get("assessments", []))
    attempt_rows = get_ai_tutor_attempts(int(session["id"]))
    attempts = [
        {
            "question": row["question"],
            "user_answer": row["user_answer"],
            "is_correct": bool(row["is_correct"]),
            "mistake_type": row["mistake_type"],
        }
        for row in attempt_rows
    ]
    summary = conversation_summary(
        session["focus_concept_id"],
        _message_dicts(rows),
        assessments,
        attempts,
    )
    correct_count = sum(bool(item["is_correct"]) for item in attempts)
    finalize_ai_tutor_attempts(
        int(session["id"]),
        session["focus_concept_id"],
        correct_count,
        summary["rating"],
        summary["content"],
    )
    summary_id = finish_tutor_session(session["id"], summary)
    mastery_row = get_concept_mastery()[session["focus_concept_id"]]
    final_mastery = float(mastery_row["mastery"])
    consecutive_correct = 0
    for assessment in reversed(assessments):
        if assessment != "correct":
            break
        consecutive_correct += 1
    return summary_id, {
        "concept": get_concept(session["focus_concept_id"])["concept"],
        "initial_mastery": float(context.get("initial_mastery", 0.0)),
        "final_mastery": final_mastery,
        "consecutive_correct": consecutive_correct,
        "rating": summary["rating"],
    }


def _render_growth_reward(reward: dict[str, Any] | None) -> None:
    if not reward:
        return
    before = _voyager_rank(float(reward["initial_mastery"]))
    after = _voyager_rank(float(reward["final_mastery"]))
    streak = int(reward["consecutive_correct"])
    streak_copy = (
        "你已经能更稳定地使用："
        if streak >= 2
        else "你刚刚认真探索了："
    )
    if reward.get("rating"):
        status = escape(str(reward["rating"]))
    elif before != after:
        status = (
            f"{before[0]} {before[1]}"
            f"<br><span style='color:#9a7b32;'>↓</span><br>"
            f"{after[0]} {after[1]}"
        )
    else:
        status = f"{after[0]} {after[1]}，正在稳稳前行"
    st.markdown(
        f"""
        <div class="warm-card reward-card">
            <div class="warm-card-title">🎉 噜噜发现</div>
            <div class="warm-card-copy">
                {escape(streak_copy)}<br>
                <strong>{escape(reward['concept'])}</strong>
                <br><br>
                <span class="warm-card-label">航海身份</span><br>
                {status}
                <br><br>
                不是坐了多久，而是真的又多懂了一点。
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_completed_summary(summary_id: int) -> None:
    summary = get_summary(summary_id)
    if not summary:
        return
    st.markdown(
        """
        <div class="lulu-note">
        今天愿意坐下来认真想、认真回答，就已经很棒啦。不会的地方不是失败，
        是噜噜下一次陪你继续努力的方向。先收下噜噜的鼓励！
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_cropped_video(LULU_FINISH_VIDEO)
    _render_growth_reward(st.session_state.get("growth_reward"))
    st.subheader("噜噜给你的学习总结")
    st.markdown(_chat_markdown(summary["content"]))
    favorite = st.toggle(
        "收藏这份总结",
        value=bool(summary["favorited"]),
        key=f"favorite_summary_{summary_id}",
    )
    if favorite != bool(summary["favorited"]):
        set_summary_favorite(summary_id, favorite)
        st.toast("已收藏" if favorite else "已取消收藏")

    reflection = st.text_area(
        "记录一个顿悟或重要反思",
        placeholder="例如：条件概率不是多背一个公式，而是样本空间发生了变化。",
        key=f"reflection_{summary_id}",
    )
    if reflection and st.button("收藏这条反思", key=f"save_reflection_{summary_id}"):
        save_favorite_reflection(reflection, summary["review_focus"])
        st.success("反思已收藏。")

    if st.button("开始新的学习", type="primary", width="stretch"):
        st.session_state.pop("completed_summary_id", None)
        st.session_state.pop("active_tutor_session_id", None)
        st.session_state["learning_mode"] = "tree"
        st.session_state.pop("growth_reward", None)
        st.rerun()


def _concept_rank_label(
    concept_key: str,
    mastery_rows: dict[str, Any],
) -> str:
    row = mastery_rows.get(concept_key)
    if not row or int(row["attempts"]) == 0:
        return "○ 尚未探索"
    emoji, name = _voyager_rank(float(row["mastery"]))
    return f"{emoji} {name}"


def _is_explored(
    concept_key: str,
    mastery_rows: dict[str, Any],
) -> bool:
    row = mastery_rows.get(concept_key)
    return bool(row and int(row["attempts"]) > 0)


def _first_unexplored_section_id(sections: list[dict[str, Any]]) -> str:
    for section in sections:
        if int(section["attempts"]) == 0:
            return str(section["id"])
    return min(
        sections,
        key=lambda section: (
            int(section["correct_attempts"]) / int(section["attempts"])
            if int(section["attempts"])
            else 0.0
        ),
    )["id"]


def _section_rank(section: dict[str, Any]) -> str:
    attempts = int(section["attempts"])
    if not attempts:
        return "○ 尚未探索"
    accuracy = int(section["correct_attempts"]) / attempts
    emoji, name = _voyager_rank(accuracy)
    return f"{emoji} {name}"


def _render_topic_tree() -> None:
    hero_copy = _render_ocean_hero(
        "learning",
        LULU_LEARNING_SCENE,
        "知识航线",
        "下一座想靠岸的知识岛在哪里？",
        "你可以选择跟噜按顺序探索，也可以自由选择章节。",
    )
    sections = get_question_bank_sections()
    if not sections:
        st.error("固定题库尚未导入。请先运行题库导入脚本。")
        return
    with hero_copy:
        st.button(
            "跟噜走",
            type="primary",
            width="stretch",
            on_click=_go_learning,
            args=(_first_unexplored_section_id(sections),),
        )

    phase_names = {
        "foundation": "基础题",
        "enhancement": "强化题",
        "comprehensive": "综合题",
        "extension": "拓展题",
    }
    subject_names = {
        "calculus": "高等数学",
        "linear_algebra": "线性代数",
        "probability": "概率论与数理统计",
    }
    sources: dict[str, list[dict[str, Any]]] = {}
    for section in sections:
        sources.setdefault(str(section["source_label"]), []).append(section)
    source_tabs = st.tabs(list(sources))
    for source_tab, source_item in zip(
        source_tabs,
        sources.items(),
        strict=True,
    ):
        _, source_sections = source_item
        with source_tab:
            for subject in ("calculus", "linear_algebra", "probability"):
                subject_sections = [
                    item
                    for item in source_sections
                    if item["subject"] == subject
                ]
                if not subject_sections:
                    continue
                chapters = len(
                    {
                        int(item["chapter_number"])
                        for item in subject_sections
                    }
                )
                with st.expander(
                    f"{subject_names[subject]} · {chapters} 个章节",
                    expanded=False,
                ):
                    for section in subject_sections:
                        attempts = int(section["attempts"])
                        correct = int(section["correct_attempts"])
                        answered = int(section["answered_questions"])
                        total_questions = int(section["question_count"])
                        accuracy = correct / attempts if attempts else 0.0
                        coverage = (
                            answered / total_questions
                            if total_questions
                            else 0.0
                        )
                        copy, action = st.columns(
                            [4, 1.2],
                            vertical_alignment="center",
                        )
                        copy.markdown(
                            f"**{section['title']}**　{_section_rank(section)}"
                        )
                        phase_label = phase_names.get(
                            str(section["phase"]),
                            str(section["phase"]),
                        )
                        copy.caption(
                            f"{phase_label} · {total_questions} 题"
                            + (
                                f" · 已答 {answered} 题 · 正确率 {accuracy:.0%}"
                                if attempts
                                else " · 尚未开始"
                            )
                        )
                        copy.progress(
                            coverage,
                            text=f"题库探索进度 {answered}/{total_questions}",
                        )
                        if action.button(
                            "开始探索",
                            key=f"bank_start_{section['id']}",
                            type="primary",
                            width="stretch",
                        ):
                            _go_learning(str(section["id"]))
                            st.rerun()
                        st.divider()

    with st.popover("AI 设置"):
        tutor = AITutor()
        st.caption(f"OpenRouter 模型：{tutor.model}")
        st.caption("API Key 已配置" if tutor.enabled else "API Key 尚未配置")
        if st.button("测试噜噜导师连接", key="test_openrouter_connection"):
            try:
                with st.spinner("正在连接 OpenRouter…"):
                    connected = tutor.test_connection()
                if connected:
                    st.success("噜噜导师连接成功")
            except AIServiceError as exc:
                st.error(str(exc))


def _normal_answer(value: str) -> str:
    import unicodedata

    value = unicodedata.normalize("NFKC", value)
    value = value.replace("，", ",").replace("。", "")
    return re.sub(r"\s+", "", value).lower()


def _start_bank_session(section_id: str) -> dict[str, Any]:
    questions = choose_question_bank_questions(section_id, 5)
    if not questions:
        raise RuntimeError("这个章节暂时没有可用题目。")
    session = {
        "section_id": section_id,
        "questions": questions,
        "index": 0,
        "results": [],
        "feedback": {},
        "complete": False,
    }
    st.session_state["bank_session"] = session
    return session


def _record_bank_result(
    session: dict[str, Any],
    question: dict[str, Any],
    user_answer: str,
    is_correct: bool,
) -> None:
    if question["id"] in session["feedback"]:
        return
    record_question_bank_attempt(question, user_answer, is_correct)
    result = {"question_id": question["id"], "is_correct": is_correct}
    session["results"].append(result)
    session["feedback"][question["id"]] = {
        "is_correct": is_correct,
        "user_answer": user_answer,
    }
    st.session_state["bank_session"] = session


def _render_question_tutor(
    *,
    question_id: str,
    section_title: str,
    question_text: str,
    answer_text: str,
    question_images: list[str],
    key_prefix: str,
) -> None:
    history_key = f"{key_prefix}_dialogue_{question_id}"
    summary_key = f"{key_prefix}_summary_{question_id}"
    history = st.session_state.setdefault(history_key, [])
    summary_id = st.session_state.get(summary_key)

    for message in history:
        avatar = (
            str(USER_AVATAR_IMAGE)
            if message["role"] == "user"
            else str(LULU_TUTOR_IMAGE)
        )
        with st.chat_message(message["role"], avatar=avatar):
            st.markdown(_chat_markdown(message["content"]))

    if summary_id:
        summary = get_summary(int(summary_id))
        if summary:
            for path in json.loads(summary["question_images_json"] or "[]"):
                st.image(str(BASE_DIR / path), width="stretch")
            st.markdown(_chat_markdown(summary["content"]))
            favorite = st.toggle(
                "收藏这份总结",
                value=bool(summary["favorited"]),
                key=f"{key_prefix}_favorite_{summary_id}",
            )
            if favorite != bool(summary["favorited"]):
                set_summary_favorite(int(summary_id), favorite)
                st.toast("已收藏" if favorite else "已取消收藏")
        return

    with st.form(
        f"{key_prefix}_form_{question_id}",
        clear_on_submit=True,
    ):
        doubt = st.text_input(
            "继续问噜噜" if history else "具体哪里不理解？",
            placeholder=(
                "继续说你卡住的地方……"
                if history
                else "例如：为什么这里要换元？"
            ),
        )
        submitted = st.form_submit_button(
            "继续请教" if history else "请教噜噜",
        )

    if submitted:
        doubt = doubt.strip()
        if not doubt:
            st.warning("先告诉噜噜你具体卡在哪里。")
        else:
            try:
                with st.spinner("噜噜正在结合这道题和刚才的对话思考…"):
                    explanation = AITutor().explain_question(
                        section_title=section_title,
                        question_text=question_text,
                        answer_text=answer_text,
                        user_question=doubt,
                        recent_dialogue=history[-10:],
                    )
                history.extend(
                    [
                        {"role": "user", "content": doubt},
                        {"role": "assistant", "content": explanation},
                    ]
                )
                st.session_state[history_key] = history
                st.rerun()
            except AIServiceError as exc:
                st.error(str(exc))

    if history and st.button(
        "结束请教并生成总结",
        key=f"{key_prefix}_clear_{question_id}",
    ):
        try:
            with st.spinner("噜噜正在整理这次真正弄明白的内容…"):
                summary = AITutor().generate_question_dialogue_summary(
                    section_title=section_title,
                    question_text=question_text,
                    answer_text=answer_text,
                    dialogue=history,
                )
            summary_id = save_question_dialogue_summary(
                summary,
                question_images,
            )
            st.session_state[summary_key] = summary_id
            st.rerun()
        except AIServiceError as exc:
            st.error(str(exc))


def _render_bank_summary(session: dict[str, Any]) -> None:
    correct = sum(bool(item["is_correct"]) for item in session["results"])
    st.markdown(
        """
        <div class="lulu-note">
        本次五道题已经完成，答题记录和章节进度已保存。
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f"**完成情况：** 答对 {correct} / {len(session['questions'])} 题")
    if st.button("返回知识航线", type="primary", width="stretch"):
        st.session_state.pop("bank_session", None)
        st.session_state["learning_mode"] = "tree"
        st.rerun()


def _render_bank_question(session: dict[str, Any]) -> None:
    question = session["questions"][session["index"]]
    feedback = session["feedback"].get(question["id"])
    question_label = (
        question.get("source_question_label")
        or f"第 {question['question_number']} 题"
    )
    st.caption(
        f"{question['section_title']} · "
        f"{question_label}"
    )
    st.progress(
        len(session["results"]) / len(session["questions"]),
        text=f"本次航行 {len(session['results'])}/{len(session['questions'])}",
    )
    for path in question["question_images"]:
        st.image(str(BASE_DIR / path), width="stretch")

    answer_key = f"bank_answer_{question['id']}"
    user_answer = ""
    if question["question_type"] == "choice" or question["answer_choice"]:
        selected = st.radio(
            "选择答案",
            ["A", "B", "C", "D"],
            index=None,
            horizontal=True,
            key=answer_key,
        )
        user_answer = selected or ""
    else:
        user_answer = st.text_area(
            "写下你的答案或思路",
            key=answer_key,
            placeholder="先独立思考，再提交。",
        )

    awaiting_key = f"bank_self_check_{question['id']}"
    if not feedback and not st.session_state.get(awaiting_key):
        if st.button("提交答案", type="primary", key=f"submit_{question['id']}"):
            if not user_answer.strip():
                st.warning("先写下答案或思路。")
            elif question["auto_gradable"] and (
                question["answer_choice"] or question["answer_text"]
            ):
                expected = question["answer_choice"] or question["answer_text"]
                is_correct = _normal_answer(user_answer) == _normal_answer(expected)
                _record_bank_result(session, question, user_answer, is_correct)
                st.rerun()
            else:
                st.session_state[awaiting_key] = user_answer
                st.rerun()

    if feedback:
        if feedback["is_correct"]:
            st.image(str(LULU_CORRECT_IMAGE), width=150)
            st.success("回答正确")
        else:
            st.image(str(LULU_INCORRECT_IMAGE), width=150)
            st.error("回答错误")

    if feedback or st.session_state.get(awaiting_key):
        st.markdown("### 参考答案与解析")
        if question["answer_text"]:
            st.markdown(f"**识别到的答案：** {question['answer_text']}")
        for path in question["answer_images"]:
            st.image(str(BASE_DIR / path), width="stretch")
        if not question["answer_text"] and not question["answer_images"]:
            st.info(
                "解析册中未检出这道题的对应解析。你仍可以点击“请教噜噜”，"
                "让噜噜围绕当前题目继续讲解。"
            )

    if not feedback and st.session_state.get(awaiting_key):
        left, right = st.columns(2)
        if left.button("我答对了", key=f"self_right_{question['id']}", width="stretch"):
            answer = str(st.session_state.pop(awaiting_key))
            _record_bank_result(session, question, answer, True)
            st.rerun()
        if right.button("还需复习", key=f"self_wrong_{question['id']}", width="stretch"):
            answer = str(st.session_state.pop(awaiting_key))
            _record_bank_result(session, question, answer, False)
            st.rerun()

    st.markdown("### 请教噜噜")
    _render_question_tutor(
        question_id=question["id"],
        section_title=question["section_title"],
        question_text=question["question_text"],
        answer_text=question["answer_text"],
        question_images=question["question_images"],
        key_prefix="bank_lulu",
    )

    if feedback:
        label = (
            "完成本次航行"
            if session["index"] + 1 >= len(session["questions"])
            else "下一题"
        )
        if st.button(label, type="primary", width="stretch"):
            if session["index"] + 1 >= len(session["questions"]):
                session["complete"] = True
            else:
                session["index"] += 1
            st.session_state["bank_session"] = session
            st.rerun()


def _persist_daily(session: dict[str, Any], status: str | None = None) -> None:
    session_status = status or session.get("mode", "active")
    update_daily_session(
        int(session["daily_session_id"]),
        status=session_status,
        context=session,
        report=session.get("report"),
    )


def _daily_question_widget(question: dict[str, Any], key_prefix: str) -> str:
    answer_key = f"{key_prefix}_{question['id']}"
    if question["question_type"] == "choice" or question["answer_choice"]:
        selected = st.radio(
            "选择答案",
            ["A", "B", "C", "D"],
            index=None,
            horizontal=True,
            key=answer_key,
        )
        return selected or ""
    return st.text_area(
        "写下你的答案或思路",
        key=answer_key,
        placeholder="先独立思考，再提交。",
    )


def _render_daily_question_media(question: dict[str, Any]) -> None:
    for path in question.get("question_images", []):
        st.image(str(BASE_DIR / path), width="stretch")


def _render_daily_answer_media(question: dict[str, Any]) -> None:
    if question.get("answer_text"):
        st.markdown(f"**识别到的答案：** {question['answer_text']}")
    for path in question.get("answer_images", []):
        st.image(str(BASE_DIR / path), width="stretch")
    if not question.get("answer_text") and not question.get("answer_images"):
        st.info("题库暂未检出对应解析图片，可以在下方请教噜噜。")


def _render_react_trace(trace: list[dict[str, Any]], *, expanded: bool = False) -> None:
    if not trace:
        return
    with st.container(border=True):
        for event in trace:
            message = escape(str(event.get("message", "")))
            kind = str(event.get("kind", ""))
            prefix = "**结果**：" if kind == "结果" else ""
            st.markdown(f"- {prefix}{message}", unsafe_allow_html=True)


def _daily_record_initial(
    session: dict[str, Any],
    question: dict[str, Any],
    user_answer: str,
    is_correct: bool,
) -> None:
    record_question_bank_attempt(question, user_answer, is_correct, "daily")
    session["initial_answer"] = user_answer
    session["initial_correct"] = bool(is_correct)
    session["last_result"] = bool(is_correct)
    if is_correct:
        session["mode"] = "correct"
    else:
        session["mode"] = "wrong"
    _persist_daily(session)


def _render_daily_initial(session: dict[str, Any]) -> None:
    question = session["question"]
    label = question.get("source_question_label") or f"第 {question['question_number']} 题"
    st.caption(f"{question['section_title']} · {label}")
    st.progress(0.0, text="今日一题")
    _render_daily_question_media(question)

    pending = session.get("pending_answer")
    if not pending:
        user_answer = _daily_question_widget(question, "daily_answer")
        if st.button("提交答案", type="primary", key="daily_submit"):
            if not user_answer.strip():
                st.warning("先写下答案或思路。")
            elif question["auto_gradable"] and (
                question["answer_choice"] or question["answer_text"]
            ):
                expected = question["answer_choice"] or question["answer_text"]
                is_correct = _normal_answer(user_answer) == _normal_answer(expected)
                _daily_record_initial(session, question, user_answer, is_correct)
                st.rerun()
            else:
                session["pending_answer"] = user_answer
                _persist_daily(session)
                st.rerun()
    else:
        st.markdown("### 参考答案与解析")
        _render_daily_answer_media(question)
        left, right = st.columns(2)
        if left.button("我答对了", key="daily_self_right", width="stretch"):
            _daily_record_initial(session, question, str(pending), True)
            session.pop("pending_answer", None)
            st.rerun()
        if right.button("还需复习", key="daily_self_wrong", width="stretch"):
            _daily_record_initial(session, question, str(pending), False)
            session.pop("pending_answer", None)
            st.rerun()


def _render_daily_correct(session: dict[str, Any]) -> None:
    st.image(str(LULU_CORRECT_IMAGE), width=150)
    st.success("回答正确")
    st.markdown("这一题已经记录到你的学习档案。你可以结束今天的练习，也可以再来一道。")
    left, right = st.columns(2)
    if left.button("再来一道", type="primary", key="daily_next"):
        question = choose_daily_question(list(session.get("asked_ids", [])))
        if question:
            session["question"] = question
            session["asked_ids"] = [*session.get("asked_ids", []), question["id"]]
            session["mode"] = "question"
            session.pop("pending_answer", None)
            session.pop("initial_answer", None)
            session.pop("initial_correct", None)
            _persist_daily(session)
            st.rerun()
        st.info("当前没有找到新的每日题，今天先到这里。")
    if right.button("结束今日练习", key="daily_finish"):
        _persist_daily(session, "complete")
        st.session_state.pop("daily_session", None)
        _go_home()
        st.rerun()


def _render_daily_wrong(session: dict[str, Any]) -> None:
    question = session["question"]
    st.image(str(LULU_INCORRECT_IMAGE), width=150)
    st.error("回答错误")
    st.markdown(
        "这道题已经记录到错题档案。先不要急着看答案，点击下面的按钮，让噜噜通过对话定位真正的错因。"
    )
    with st.container(border=True):
        st.markdown("### 本题")
        _render_daily_question_media(question)
        st.caption(f"你的答案：{session.get('initial_answer', '未记录')}")
    left, right = st.columns(2)
    if left.button("错因诊断", type="primary", key="daily_diagnose_start", width="stretch"):
        try:
            with st.spinner("噜噜正在读取题目标签和你的学习记录…"):
                diagnosis = start_diagnosis(
                    daily_session_id=int(session["daily_session_id"]),
                    original_question=question,
                    original_user_answer=str(session.get("initial_answer", "")),
                )
            session["diagnosis"] = diagnosis
            session["mode"] = "diagnosis"
            _persist_daily(session)
            st.rerun()
        except AIServiceError as exc:
            st.error(str(exc))
    if right.button("先看参考答案", key="daily_wrong_answer", width="stretch"):
        session["mode"] = "wrong_answer"
        _persist_daily(session)
        st.rerun()


def _render_daily_wrong_answer(session: dict[str, Any]) -> None:
    question = session["question"]
    st.markdown("### 参考答案与解析")
    _render_daily_answer_media(question)
    if st.button("进入错因诊断", type="primary", key="daily_wrong_answer_diagnose"):
        try:
            diagnosis = start_diagnosis(
                daily_session_id=int(session["daily_session_id"]),
                original_question=question,
                original_user_answer=str(session.get("initial_answer", "")),
            )
            session["diagnosis"] = diagnosis
            session["mode"] = "diagnosis"
            _persist_daily(session)
            st.rerun()
        except AIServiceError as exc:
            st.error(str(exc))


def _daily_diagnosis_turn(session: dict[str, Any], user_message: str) -> None:
    diagnosis = session["diagnosis"]
    try:
        with st.spinner("噜噜正在根据刚才的回答决定下一步…"):
            diagnosis = diagnose_turn(
                state=diagnosis,
                user_message=user_message,
            )
        session["diagnosis"] = diagnosis
        session["mode"] = diagnosis["status"]
        _persist_daily(session)
        st.rerun()
    except AIServiceError as exc:
        st.error(str(exc))


def _render_daily_diagnosis_chat(session: dict[str, Any]) -> None:
    diagnosis = session["diagnosis"]
    question = session["question"]
    with st.container(border=True):
        st.markdown("### 噜噜正在诊断这道题")
        _render_daily_question_media(question)
        st.caption(f"你的答案：{session.get('initial_answer', '未记录')}")

    _render_react_trace(diagnosis.get("trace", []), expanded=True)
    _render_diagnosis_source(diagnosis)
    mastery_rows = diagnosis.get("prerequisite_mastery", [])
    if mastery_rows:
        st.markdown("### 前置知识掌握度")
        for item in mastery_rows:
            mastery = item["mastery"]
            attempts = int(mastery.get("attempts", 0))
            accuracy = (
                f"{float(mastery.get('accuracy', 0.0)):.0%}"
                if attempts
                else "暂无记录"
            )
            st.markdown(f"- **{item['title']}**：已答 {attempts} 次，正确率 {accuracy}")
        st.caption(
            "这些掌握度会作为噜噜的判断依据，接下来由噜噜根据你的回答决定是解释、追问还是安排题目。"
        )
    for message in diagnosis.get("dialogue", []):
        avatar = (
            str(USER_AVATAR_IMAGE)
            if message.get("role") == "user"
            else str(LULU_TUTOR_IMAGE)
        )
        with st.chat_message(message.get("role", "assistant"), avatar=avatar):
            st.markdown(_chat_markdown(message.get("content", "")))

    with st.form("daily_diagnosis_form", clear_on_submit=True):
        message = st.text_area(
            "告诉噜噜你卡在哪里",
            placeholder="例如：我不知道为什么这里要先求偏导……",
        )
        submitted = st.form_submit_button("发送给噜噜", type="primary")
    if submitted:
        if not message.strip():
            st.warning("先写下你的疑问或刚才的解题思路。")
        else:
            _daily_diagnosis_turn(session, message.strip())

    if diagnosis.get("dialogue") and st.button(
        "结束诊断并生成总结",
        key="daily_diagnosis_finish",
        width="stretch",
    ):
            _finish_daily_diagnosis(session)


def _render_diagnosis_source(diagnosis: dict[str, Any]) -> None:
    source = diagnosis.get("last_decision_source", "尚未产生决策")
    if source == "DeepSeek Agent":
        st.success("本轮决策来源：DeepSeek Agent")
    elif source.startswith("本地 Agent"):
        st.warning(f"本轮决策来源：{source}")
    else:
        st.info(f"本轮决策来源：{source}")
    step_count = int(diagnosis.get("agent_steps", 0))
    tool_duration = diagnosis.get("last_tool_duration_ms")
    if step_count or tool_duration:
        timing = f"已完成 {step_count} 轮判断"
        if tool_duration:
            timing += f"，最近一次工具查询耗时 {float(tool_duration):.0f} ms"
        st.caption(timing)
    history = diagnosis.get("decision_sources", [])
    if len(history) > 1:
        with st.expander("查看每轮决策来源"):
            for index, item in enumerate(history, start=1):
                st.markdown(f"第 {index} 轮：{item}")


def _record_daily_diagnosis_result(
    session: dict[str, Any],
    question: dict[str, Any],
    user_answer: str,
    is_correct: bool,
    attempt_type: str,
) -> None:
    record_question_bank_attempt(question, user_answer, is_correct, attempt_type)
    diagnosis = session["diagnosis"]
    diagnosis.setdefault("support_results", []).append(
        {
            "question_id": question["id"],
            "section_title": question["section_title"],
            "is_correct": bool(is_correct),
        }
    )
    diagnosis["current_question"] = None
    session["diagnosis"] = diagnosis
    result_text = (
        f"我完成了「{question['section_title']}·第{question['question_number']}题」，"
        f"这道补充题我答{'对' if is_correct else '错'}了。"
    )
    _daily_diagnosis_turn(session, result_text)


def _render_daily_diagnosis_support(session: dict[str, Any]) -> None:
    diagnosis = session["diagnosis"]
    question = diagnosis.get("current_question")
    if not question:
        session["mode"] = "diagnosis"
        _persist_daily(session)
        st.rerun()
        return
    _render_react_trace(diagnosis.get("trace", []), expanded=True)
    _render_diagnosis_source(diagnosis)
    scope_label = (
        "前置知识"
        if question.get("repair_scope") == "prerequisite"
        else "同章节"
    )
    st.info(f"噜噜根据刚才的诊断安排了一道{scope_label}题。做完后会继续回到诊断对话。")
    st.caption(f"补充题：{question['section_title']} · 第{question['question_number']}题")
    _render_daily_question_media(question)
    pending = session.get("diagnosis_support_pending")
    if not pending:
        user_answer = _daily_question_widget(question, "daily_diagnosis_support")
        if st.button("提交补充题", type="primary", key="daily_diagnosis_support_submit"):
            if not user_answer.strip():
                st.warning("先写下答案或思路。")
            elif question["auto_gradable"] and (
                question["answer_choice"] or question["answer_text"]
            ):
                expected = question["answer_choice"] or question["answer_text"]
                is_correct = _normal_answer(user_answer) == _normal_answer(expected)
                _record_daily_diagnosis_result(
                    session, question, user_answer, is_correct, "react_diagnosis_support"
                )
            else:
                session["diagnosis_support_pending"] = user_answer
                _persist_daily(session)
                st.rerun()
    else:
        st.markdown("### 参考答案与解析")
        _render_daily_answer_media(question)
        left, right = st.columns(2)
        if left.button("补充题答对了", key="daily_diagnosis_support_right", width="stretch"):
            answer = str(session.pop("diagnosis_support_pending"))
            _record_daily_diagnosis_result(
                session, question, answer, True, "react_diagnosis_support"
            )
        if right.button("补充题仍需复习", key="daily_diagnosis_support_wrong", width="stretch"):
            answer = str(session.pop("diagnosis_support_pending"))
            _record_daily_diagnosis_result(
                session, question, answer, False, "react_diagnosis_support"
            )


def _render_daily_diagnosis_retest(session: dict[str, Any]) -> None:
    diagnosis = session["diagnosis"]
    question = session["question"]
    _render_react_trace(diagnosis.get("trace", []), expanded=True)
    _render_diagnosis_source(diagnosis)
    st.info("噜噜认为可以回到原题验证了。请重新作答，不必追求一次写得很完整。")
    _render_daily_question_media(question)
    pending = session.get("diagnosis_retest_pending")
    if not pending:
        user_answer = _daily_question_widget(question, "daily_diagnosis_retest")
        if st.button("提交原题验证", type="primary", key="daily_diagnosis_retest_submit"):
            if not user_answer.strip():
                st.warning("先写下答案或思路。")
            elif question["auto_gradable"] and (
                question["answer_choice"] or question["answer_text"]
            ):
                expected = question["answer_choice"] or question["answer_text"]
                is_correct = _normal_answer(user_answer) == _normal_answer(expected)
                if is_correct:
                    resolve_wrong_question(question["id"])
                _record_daily_diagnosis_result(
                    session, question, user_answer, is_correct, "react_diagnosis_retest"
                )
            else:
                session["diagnosis_retest_pending"] = user_answer
                _persist_daily(session)
                st.rerun()
    else:
        st.markdown("### 参考答案与解析")
        _render_daily_answer_media(question)
        left, right = st.columns(2)
        if left.button("原题已经弄明白", key="daily_diagnosis_retest_right", width="stretch"):
            answer = str(session.pop("diagnosis_retest_pending"))
            resolve_wrong_question(question["id"])
            _record_daily_diagnosis_result(
                session, question, answer, True, "react_diagnosis_retest"
            )
        if right.button("原题仍需复习", key="daily_diagnosis_retest_wrong", width="stretch"):
            answer = str(session.pop("diagnosis_retest_pending"))
            _record_daily_diagnosis_result(
                session, question, answer, False, "react_diagnosis_retest"
            )


def _finish_daily_diagnosis(session: dict[str, Any]) -> None:
    question = session["question"]
    diagnosis = session["diagnosis"]
    try:
        with st.spinner("噜噜正在根据这次对话生成本题总结…"):
            summary = AITutor().generate_question_dialogue_summary(
                section_title=question["section_title"],
                question_text=question["question_text"],
                answer_text=question.get("answer_text") or question.get("answer_choice", ""),
                dialogue=diagnosis.get("dialogue", []),
            )
        summary_id = save_question_dialogue_summary(
            summary,
            question.get("question_images", []),
        )
        close_diagnosis(diagnosis, summary)
        session["diagnosis"] = diagnosis
        session["report"] = summary
        session["summary_id"] = summary_id
        session["mode"] = "diagnosis_report"
        _persist_daily(session, "complete")
        st.rerun()
    except AIServiceError as exc:
        st.error(str(exc))


def _render_daily_diagnosis_report(session: dict[str, Any]) -> None:
    report = session.get("report", {})
    st.markdown("## 本题错因诊断总结")
    diagnosis = session.get("diagnosis", {})
    _render_react_trace(diagnosis.get("trace", []))
    st.markdown(_chat_markdown(report.get("content", "本次诊断已经结束。")))
    summary_id = session.get("summary_id")
    if summary_id:
        summary = get_summary(int(summary_id))
        if summary:
            favorite = st.toggle(
                "收藏这份总结",
                value=bool(summary["favorited"]),
                key=f"daily_diagnosis_favorite_{summary_id}",
            )
            if favorite != bool(summary["favorited"]):
                set_summary_favorite(int(summary_id), favorite)
                st.toast("已收藏" if favorite else "已取消收藏")
    if st.button("返回每日一题", type="primary", key="daily_diagnosis_report_home"):
        st.session_state.pop("daily_session", None)
        _go_home()
        st.rerun()


def render_daily() -> None:
    _render_back_arrow("home", "daily")
    session = st.session_state.get("daily_session")
    if not session:
        question = choose_daily_question()
        if not question:
            st.error("固定题库中暂时没有可用题目。")
            return
        session = {
            "mode": "question",
            "question": question,
            "asked_ids": [question["id"]],
            "daily_session_id": start_daily_session(
                question["id"],
                {"mode": "question", "question_id": question["id"]},
            ),
        }
        st.session_state["daily_session"] = session

    _render_ocean_hero(
        "daily",
        LULU_LEARNING_SCENE,
        "每日一题",
        "今天先解决一个真正的漏洞",
        "答错后，噜噜会根据你的学习记录安排有限的知识补全。",
    )
    mode = session.get("mode")
    if mode == "question":
        _render_daily_initial(session)
    elif mode == "correct":
        _render_daily_correct(session)
    elif mode == "wrong":
        _render_daily_wrong(session)
    elif mode == "wrong_answer":
        _render_daily_wrong_answer(session)
    elif mode == "diagnosis":
        _render_daily_diagnosis_chat(session)
    elif mode == "diagnosis_complete":
        _render_daily_diagnosis_chat(session)
    elif mode == "diagnosis_support":
        _render_daily_diagnosis_support(session)
    elif mode == "diagnosis_retest":
        _render_daily_diagnosis_retest(session)
    elif mode == "diagnosis_report":
        _render_daily_diagnosis_report(session)


def render_learning() -> None:
    mode = st.session_state.get("learning_mode", "tree")
    _render_back_arrow("home" if mode == "tree" else "learning", "learning")
    if mode == "tree":
        _render_topic_tree()
        return

    requested = st.session_state.pop("requested_section_id", None)
    session = st.session_state.get("bank_session")
    if requested or not session:
        try:
            if not requested:
                requested = _first_unexplored_section_id(
                    get_question_bank_sections()
                )
            session = _start_bank_session(str(requested))
        except RuntimeError as exc:
            st.error(str(exc))
            return

    section_id = str(session["section_id"])
    paused = _touch_activity(section_id)
    if paused:
        st.warning("超过 5 分钟没有互动，学习计时已暂停；现在已重新开始。")

    _render_ocean_hero(
        "tutor",
        LULU_LEARNING_SCENE,
        "固定题库航行",
        str(session["questions"][0]["section_title"]),
        "先独立作答，需要时再请教噜噜。",
    )
    if session["complete"]:
        _render_bank_summary(session)
    else:
        _render_bank_question(session)


def _selected_indices(question: dict[str, Any], key: str) -> list[int]:
    if question["type"] == "multiple":
        labels = st.multiselect(
            "选择所有正确选项",
            question["options"],
            key=key,
            format_func=_plain_math,
            placeholder="请选择所有正确选项",
        )
        return [question["options"].index(label) for label in labels]
    label = st.radio(
        "请选择",
        question["options"],
        index=None,
        key=key,
        format_func=_plain_math,
        horizontal=question["type"] == "boolean",
    )
    return [question["options"].index(label)] if label is not None else []


def _plain_math(text: str) -> str:
    """Make LaTeX-backed options readable inside non-Markdown widgets."""
    replacements = {
        r"\mid": " | ",
        r"\le": "≤",
        r"\ge": "≥",
        r"\ne": "≠",
        r"\times": "×",
        r"\cap": "∩",
        r"\cup": "∪",
        r"\subset": "⊂",
        r"\varnothing": "∅",
        r"\Omega": "Ω",
        r"\ldots": "…",
        r"\to": "→",
    }
    value = text.replace("$", "")
    for source, target in replacements.items():
        value = value.replace(source, target)
    value = re.sub(r"\\overline\s*\{([^{}]+)\}", r"\1 的对立事件", value)
    value = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"(\1)/(\2)", value)
    value = value.replace("\\", "")
    return re.sub(r"\s+", " ", value).strip()


def _markdown_math(text: str) -> str:
    """Keep Chinese text outside math delimiters from sticking to LaTeX."""
    return re.sub(r"\$([^$]+)\$(?=[\u4e00-\u9fff])", r"$\1$ ", text)


def _chat_markdown(value: Any) -> str:
    r"""Normalize common LaTeX delimiters before rendering chat Markdown.

    Streamlit renders math in Markdown with ``$...$`` and ``$$...$$``. Models
    commonly return the equivalent LaTeX delimiters ``\(...\)`` and
    ``\[...\]``; without this conversion those delimiters are shown literally.
    """
    text = str(value or "")
    # Responses can contain escaped delimiters when they pass through JSON.
    text = text.replace(r"\\(", r"\(")
    text = text.replace(r"\\)", r"\)")
    text = text.replace(r"\\[", r"\[")
    text = text.replace(r"\\]", r"\]")

    text = re.sub(
        r"\\\[(.*?)\\\]",
        lambda match: f"\n\n$$\n{match.group(1).strip()}\n$$\n\n",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\\\((.*?)\\\)",
        lambda match: f"${match.group(1).strip()}$",
        text,
        flags=re.DOTALL,
    )
    return _markdown_math(text)


def _answer_text(question: dict[str, Any], indices: list[int]) -> str:
    return "；".join(question["options"][index] for index in indices)


def _question_from_wrong(row: Any) -> dict[str, Any] | None:
    if row["question_json"]:
        try:
            return json.loads(row["question_json"])
        except json.JSONDecodeError:
            pass
    question = get_question(row["question_id"])
    if question:
        question = dict(question)
        question["id"] = row["question_id"]
    return question


def render_wrong_book() -> None:
    _render_back_arrow("home", "wrong")
    _render_ocean_hero(
        "wrong",
        LULU_WRONG_SCENE,
        "触礁记录",
        "每一次触礁，都能让下一次航行更稳",
        "这里保存真实学习中答错过的题目。先按自己的思路重新作答，再查看答案和解析。",
    )
    include_resolved = st.checkbox("看看已经修补好的暗礁")
    rows = get_wrong_questions(include_resolved)
    if not rows:
        st.info("海面很平静，当前没有等待修补的暗礁。")
        return

    for row in rows:
        question = _question_from_wrong(row)
        if not question:
            continue
        if question.get("source") == "fixed_question_bank":
            status = "已修补" if row["resolved"] else "等待修补"
            with st.expander(
                f"{status} · {question['section_title']} · "
                f"{question['id'].rsplit('-q', 1)[-1]} 题"
            ):
                for path in question.get("question_images", []):
                    st.image(str(BASE_DIR / path), width="stretch")
                retry = st.text_area(
                    "先重新写下答案或思路",
                    key=f"reef_retry_{question['id']}",
                )
                reveal_key = f"reef_reveal_{question['id']}"
                if st.button("提交并查看解析", key=f"reef_submit_{question['id']}"):
                    if retry.strip():
                        st.session_state[reveal_key] = True
                    else:
                        st.warning("先写下答案或思路。")
                if st.session_state.get(reveal_key):
                    st.markdown(f"**上次答案：** {question['last_user_answer']}")
                    if question.get("answer_text"):
                        st.markdown(f"**识别到的答案：** {question['answer_text']}")
                    for path in question.get("answer_images", []):
                        st.image(str(BASE_DIR / path), width="stretch")
                    if st.button(
                        "这次已经弄明白",
                        key=f"reef_resolve_{question['id']}",
                        type="primary",
                    ):
                        resolve_wrong_question(question["id"])
                        st.rerun()
                st.markdown("### 请教噜噜")
                _render_question_tutor(
                    question_id=question["id"],
                    section_title=question["section_title"],
                    question_text=question["question"],
                    answer_text=question.get("answer_text", ""),
                    question_images=question.get("question_images", []),
                    key_prefix="reef_lulu",
                )
            if st.button(
                "删除这条错题记录",
                key=f"reef_delete_bank_{question['id']}",
            ):
                delete_wrong_question(question["id"])
                st.toast("已删除这条错题记录")
                st.rerun()
            continue
        try:
            topic = get_topic(row["topic_id"]) if row["topic_id"] else None
        except KeyError:
            topic = None
        topic = topic or {"id": "legacy", "topic": "旧版记录"}
        status = "已修补" if row["resolved"] else "等待修补"
        with st.expander(
            f"{status} · {topic['topic']} · {question['knowledge_point']}"
        ):
            st.markdown(f"**{question['question']}**")
            for index, option in enumerate(question["options"]):
                st.markdown(
                    f"{chr(65 + index)}. {_markdown_math(option)}"
                )

            key = f"review_{question['id']}"
            answer = _selected_indices(question, key)
            if st.button("看看这次能否绕过暗礁", key=f"submit_{key}"):
                if not answer:
                    st.warning("请先选择答案。")
                else:
                    correct = sorted(answer) == sorted(question["answer"])
                    record_attempt(question, topic["id"], answer, correct, "review")
                    st.session_state[f"review_submitted_{question['id']}"] = True
                    st.session_state[f"review_correct_{question['id']}"] = correct
                    st.session_state[f"review_answer_{question['id']}"] = answer
                    if correct:
                        resolve_wrong_question(question["id"])
                        st.success("暗礁已经看清楚了，噜噜把它标在了海图上。")
                        st.image(
                            str(LULU_CORRECT_IMAGE),
                            caption="提示正确",
                            width=180,
                        )
                    else:
                        st.error("仍不正确。先解释你的判断，再看解析中的关键条件。")
                        st.image(
                            str(LULU_INCORRECT_IMAGE),
                            caption="提示错误",
                            width=180,
                        )

            if st.session_state.get(f"review_submitted_{question['id']}"):
                submitted = st.session_state.get(
                    f"review_answer_{question['id']}", []
                )
                selected = json.loads(row["last_selected_answer"] or "[]")
                selected_text = (
                    _answer_text(question, selected)
                    if selected
                    else question.get("last_user_answer", "旧版未记录")
                )
                st.divider()
                st.markdown(
                    f"**本次答案：** "
                    f"{_markdown_math(_answer_text(question, submitted))}"
                )
                st.markdown(
                    f"**上次错误答案：** {_markdown_math(selected_text)}"
                )
                st.markdown(
                    f"**正确答案：** "
                    f"{_markdown_math(_answer_text(question, question['answer']))}"
                )
                st.markdown(
                    f"**解析：** {_markdown_math(question['explanation'])}"
                )
            if st.button("让噜噜提示", key=f"hint_{question['id']}"):
                with st.chat_message("assistant", avatar=str(LULU_TUTOR_IMAGE)):
                    st.write_stream(
                        tutor_stream(
                            question["question"],
                            question["options"],
                            question["knowledge_point"],
                            topic["topic"],
                        )
                    )
            if st.button(
                "删除这条错题记录",
                key=f"reef_delete_legacy_{question['id']}",
            ):
                delete_wrong_question(question["id"])
                st.toast("已删除这条错题记录")
                st.rerun()


def render_favorites() -> None:
    _render_back_arrow("home", "favorites")
    _render_ocean_hero(
        "favorites",
        LULU_FAVORITES_SCENE,
        "发现宝藏",
        "把闪光的想法装进宝箱",
        "这里收藏学习总结、顿悟时刻和重要反思。需要的时候，再回来看看曾经发现过的光。",
    )
    rows = get_summaries(100, favorites_only=True)
    if not rows:
        st.info("宝箱还是空的。完成一次航行后，可以收藏总结或记下一条顿悟。")
        return

    for row in rows:
        label = row["review_focus"] or "学习反思"
        with st.container(border=True, key=f"favorite_card_{row['id']}"):
            head, action = st.columns([4, 1], vertical_alignment="center")
            head.markdown(f"**{label}**")
            head.caption(row["created_at"][:16].replace("T", " "))
            if action.button("移出宝箱", key=f"unfavorite_{row['id']}"):
                set_summary_favorite(int(row["id"]), False)
                st.rerun()
            for path in json.loads(row["question_images_json"] or "[]"):
                st.image(str(BASE_DIR / path), width="stretch")
            st.markdown(_chat_markdown(row["content"]))
