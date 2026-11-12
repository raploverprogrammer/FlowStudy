from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "flowstudy.db"
ASSETS_DIR = BASE_DIR / "assets" / "lulu"
LULU_TUTOR_IMAGE = ASSETS_DIR / "images" / "tutor.jpg"
LULU_PET_IMAGE = ASSETS_DIR / "images" / "pet-transparent.png"
LULU_CORRECT_IMAGE = ASSETS_DIR / "images" / "correct.jpg"
LULU_INCORRECT_IMAGE = ASSETS_DIR / "images" / "incorrect.jpg"
LULU_FLOWER_IMAGE = ASSETS_DIR / "images" / "flower.jpg"
USER_AVATAR_IMAGE = ASSETS_DIR / "images" / "user-avatar.jpg"
LULU_WELCOME_VIDEO = ASSETS_DIR / "videos" / "welcome.mp4"
LULU_CHEER_VIDEO = ASSETS_DIR / "videos" / "cheer.mp4"
LULU_FINISH_VIDEO = ASSETS_DIR / "videos" / "finish.mp4"
# WebP keeps the same 1672x941 artwork while reducing rerun payloads by over 95%.
LULU_HOME_SCENE = ASSETS_DIR / "scenes" / "home-wave.webp"
LULU_LEARNING_SCENE = ASSETS_DIR / "scenes" / "learning-telescope.webp"
LULU_WRONG_SCENE = ASSETS_DIR / "scenes" / "wrong-reef.webp"
LULU_LOG_SCENE = ASSETS_DIR / "scenes" / "log-journal.webp"
LULU_FAVORITES_SCENE = ASSETS_DIR / "scenes" / "favorites-treasure.webp"
LULU_WELCOME_PORTRAIT = ASSETS_DIR / "scenes" / "lulu-welcome-portrait.webp"
LULU_WELCOME_LANDSCAPE = ASSETS_DIR / "scenes" / "lulu-welcome-landscape.webp"
LULU_CHAT_SCENE = ASSETS_DIR / "scenes" / "lulu-chat-graffiti-desktop.webp"


def static_asset_url(path: Path) -> str:
    """Return the browser URL for an asset mirrored under the static folder."""
    relative = path.relative_to(ASSETS_DIR).as_posix()
    return f"/app/static/lulu/{relative}"


def get_secret(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value

    try:
        import streamlit as st

        return str(st.secrets.get(name, default))
    except Exception:
        return default


OPENROUTER_MODEL = "deepseek/deepseek-chat"
