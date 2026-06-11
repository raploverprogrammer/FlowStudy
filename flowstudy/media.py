from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

import streamlit.components.v1 as components


@lru_cache(maxsize=4)
def _video_data_url(path: str) -> str:
    data = Path(path).read_bytes()
    return "data:video/mp4;base64," + base64.b64encode(data).decode("ascii")


def render_cropped_video(path: Path, height: int = 540) -> None:
    """Render a silent looping video without controls or visible edge bars."""
    source = _video_data_url(str(path))
    components.html(
        f"""
        <div class="lulu-video">
          <video id="lulu-finish-video" autoplay muted loop playsinline
                 preload="auto" disablepictureinpicture>
            <source src="{source}" type="video/mp4">
          </video>
        </div>
        <style>
          html, body {{
            margin: 0;
            padding: 0;
            background: transparent;
            overflow: hidden;
          }}
          .lulu-video {{
            height: {height}px;
            width: 100%;
            overflow: hidden;
            border-radius: 18px;
            background: #fff8df;
          }}
          video {{
            width: 100%;
            height: calc(100% + 12px);
            margin-top: -6px;
            display: block;
            object-fit: cover;
            transform: scale(1.015);
            pointer-events: none;
          }}
        </style>
        <script>
          const video = document.getElementById("lulu-finish-video");
          video.muted = true;
          video.defaultMuted = true;
          video.controls = false;

          function ensurePlaying() {{
            const promise = video.play();
            if (promise) {{
              promise.catch(() => {{
                window.setTimeout(ensurePlaying, 180);
              }});
            }}
          }}

          video.addEventListener("loadeddata", ensurePlaying);
          video.addEventListener("canplay", ensurePlaying);
          video.addEventListener("pause", ensurePlaying);
          document.addEventListener("visibilitychange", () => {{
            if (!document.hidden) ensurePlaying();
          }});
          ensurePlaying();
        </script>
        """,
        height=height,
        scrolling=False,
    )
