from __future__ import annotations

import streamlit as st

from flowstudy.config import LULU_TUTOR_IMAGE
from flowstudy.database import init_db
from flowstudy.styles import apply_styles
from flowstudy.views import (
    render_home,
    render_favorites,
    render_learning,
    render_wrong_book,
    sync_study_timer,
)


st.set_page_config(
    page_title="FlowStudy",
    page_icon=str(LULU_TUTOR_IMAGE),
    layout="centered",
    initial_sidebar_state="collapsed",
)

init_db()
apply_styles()

PAGES = {
    "home": render_home,
    "learning": render_learning,
    "reefs": render_wrong_book,
    "treasures": render_favorites,
}
LEGACY_PAGES = {
    "首页": "home",
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
current = st.session_state.get("app_view", st.session_state.get("nav_page", "home"))
page = LEGACY_PAGES.get(current, current)
if page not in PAGES:
    page = "home"
st.session_state["app_view"] = page

sync_study_timer(page)
PAGES[page]()
