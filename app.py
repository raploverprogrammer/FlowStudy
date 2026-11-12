from __future__ import annotations

import streamlit as st

from flowstudy.config import LULU_TUTOR_IMAGE
from flowstudy.database import init_db
from flowstudy.pet import render_lulu_pet
from flowstudy.styles import apply_styles
from flowstudy.views import (
    render_daily,
    render_home,
    render_favorites,
    render_learning,
    render_lulu_chat,
    render_welcome,
    render_wrong_book,
    sync_study_timer,
    _discard_lulu_chat,
)


st.set_page_config(
    page_title="FlowStudy",
    page_icon=str(LULU_TUTOR_IMAGE),
    layout="centered",
    initial_sidebar_state="collapsed",
)

@st.cache_resource(show_spinner=False)
def _initialize_database() -> None:
    """Initialize the schema once per Streamlit process, not on every rerun."""
    init_db()


_initialize_database()
apply_styles()

PAGES = {
    "welcome": render_welcome,
    "home": render_home,
    "daily": render_daily,
    "learning": render_learning,
    "lulu_chat": render_lulu_chat,
    "reefs": render_wrong_book,
    "treasures": render_favorites,
}
LEGACY_PAGES = {
    "首页": "welcome",
    "每日一题": "daily",
    "学习": "learning",
    "知识航线": "learning",
    "错题记录": "reefs",
    "暗礁修补": "reefs",
    "触礁记录": "reefs",
    "我的收藏": "treasures",
    "发现宝藏": "treasures",
    "学习记录": "home",
    "航海日志": "home",
}
current = st.query_params.get("page", "welcome")
page = LEGACY_PAGES.get(current, current)
if page not in PAGES:
    page = "welcome"
if st.query_params.get("page") != page and not (
    page == "welcome" and not st.query_params.get("page")
):
    st.query_params["page"] = page
previous_page = st.session_state.get("app_view")
if previous_page == "lulu_chat" and page != "lulu_chat":
    # Cover browser back/direct URL navigation in addition to in-app buttons.
    _discard_lulu_chat()
if page == "daily" and previous_page != "daily":
    st.session_state.pop("daily_session", None)
if page == "learning" and previous_page != "learning":
    st.session_state["learning_mode"] = "tree"
    st.session_state.pop("bank_session", None)
    st.session_state.pop("requested_section_id", None)
st.session_state["app_view"] = page

sync_study_timer(page)
PAGES[page]()
if page not in {"welcome", "lulu_chat"}:
    render_lulu_pet()
