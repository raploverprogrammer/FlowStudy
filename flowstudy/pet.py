from __future__ import annotations

import base64

import streamlit as st
import streamlit.components.v1 as components

from flowstudy.config import LULU_PET_IMAGE


def _image_data_url() -> str:
    encoded = base64.b64encode(LULU_PET_IMAGE.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def render_lulu_pet() -> None:
    """Mount one draggable pet in the parent Streamlit document."""
    html = """
    <script>
    (() => {
      const doc = window.parent.document;
      const win = window.parent;
      const storageKey = "flowstudy-lulu-pet-position-v1";
      const petWidth = 150;
      const petHeight = 218;
      let root = doc.getElementById("flowstudy-lulu-pet");

      function clamp(value, min, max) {
        return Math.min(Math.max(value, min), Math.max(min, max));
      }

      function defaultPosition() {
        const card = doc.querySelector(".growth-card");
        if (card) {
          const rect = card.getBoundingClientRect();
          return {
            x: clamp(rect.right - petWidth - 26, 8, win.innerWidth - petWidth - 8),
            y: clamp(rect.top + 18, 8, win.innerHeight - petHeight - 8)
          };
        }
        return {
          x: Math.max(8, win.innerWidth - petWidth - 28),
          y: Math.max(8, win.innerHeight - petHeight - 28)
        };
      }

      function savedPosition() {
        try {
          const saved = JSON.parse(win.localStorage.getItem(storageKey));
          if (Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
            return {
              x: clamp(saved.x, 8, win.innerWidth - petWidth - 8),
              y: clamp(saved.y, 8, win.innerHeight - petHeight - 8)
            };
          }
        } catch (_) {}
        return defaultPosition();
      }

      if (!root) {
        root = doc.createElement("div");
        root.id = "flowstudy-lulu-pet";
        root.innerHTML = `
          <div class="flowstudy-lulu-bubble">粉粉加油！</div>
          <img alt="噜噜导师" draggable="false">
        `;
        const style = doc.createElement("style");
        style.id = "flowstudy-lulu-pet-style";
        style.textContent = `
          #flowstudy-lulu-pet {
            position: fixed;
            width: ${petWidth}px;
            height: ${petHeight}px;
            z-index: 999999;
            cursor: grab;
            touch-action: none;
            user-select: none;
            -webkit-user-select: none;
          }
          #flowstudy-lulu-pet.dragging { cursor: grabbing; }
          #flowstudy-lulu-pet img {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            object-fit: contain;
            pointer-events: none;
            filter: drop-shadow(0 9px 10px rgba(89, 91, 75, .18));
          }
          #flowstudy-lulu-pet .flowstudy-lulu-bubble {
            position: absolute;
            left: 50%;
            top: -42px;
            transform: translateX(-50%) translateY(8px);
            padding: 9px 15px;
            border: 2px solid #f2b24f;
            border-radius: 18px;
            background: #fff7d7;
            color: #7b5322;
            font: 700 15px/1.2 system-ui, sans-serif;
            white-space: nowrap;
            box-shadow: 0 8px 20px rgba(113, 82, 35, .14);
            opacity: 0;
            transition: opacity .18s ease, transform .18s ease;
            pointer-events: none;
          }
          #flowstudy-lulu-pet .flowstudy-lulu-bubble::after {
            content: "";
            position: absolute;
            left: 50%;
            bottom: -7px;
            width: 11px;
            height: 11px;
            background: #fff7d7;
            border-right: 2px solid #f2b24f;
            border-bottom: 2px solid #f2b24f;
            transform: translateX(-50%) rotate(45deg);
          }
          #flowstudy-lulu-pet.show-bubble .flowstudy-lulu-bubble {
            opacity: 1;
            transform: translateX(-50%) translateY(0);
          }
        `;
        if (!doc.getElementById(style.id)) doc.head.appendChild(style);
        doc.body.appendChild(root);

        const position = savedPosition();
        root.style.left = `${position.x}px`;
        root.style.top = `${position.y}px`;

        let pointerId = null;
        let startX = 0;
        let startY = 0;
        let originX = 0;
        let originY = 0;
        let moved = false;
        let bubbleTimer = null;

        root.addEventListener("pointerdown", (event) => {
          pointerId = event.pointerId;
          startX = event.clientX;
          startY = event.clientY;
          originX = parseFloat(root.style.left) || 0;
          originY = parseFloat(root.style.top) || 0;
          moved = false;
          root.classList.add("dragging");
          root.setPointerCapture(pointerId);
          event.preventDefault();
        });

        root.addEventListener("pointermove", (event) => {
          if (event.pointerId !== pointerId) return;
          const dx = event.clientX - startX;
          const dy = event.clientY - startY;
          if (Math.abs(dx) + Math.abs(dy) > 5) moved = true;
          root.style.left = `${clamp(originX + dx, 8, win.innerWidth - petWidth - 8)}px`;
          root.style.top = `${clamp(originY + dy, 8, win.innerHeight - petHeight - 8)}px`;
        });

        root.addEventListener("pointerup", (event) => {
          if (event.pointerId !== pointerId) return;
          root.classList.remove("dragging");
          root.releasePointerCapture(pointerId);
          pointerId = null;
          win.localStorage.setItem(storageKey, JSON.stringify({
            x: parseFloat(root.style.left),
            y: parseFloat(root.style.top)
          }));
          if (!moved) {
            root.classList.add("show-bubble");
            win.clearTimeout(bubbleTimer);
            bubbleTimer = win.setTimeout(
              () => root.classList.remove("show-bubble"),
              2200
            );
          }
        });

        win.addEventListener("resize", () => {
          root.style.left = `${clamp(
            parseFloat(root.style.left) || 0,
            8,
            win.innerWidth - petWidth - 8
          )}px`;
          root.style.top = `${clamp(
            parseFloat(root.style.top) || 0,
            8,
            win.innerHeight - petHeight - 8
          )}px`;
        });
      }

      root.querySelector("img").src = "__PET_IMAGE__";
      root.style.display = "block";
    })();
    </script>
    """.replace("__PET_IMAGE__", _image_data_url())
    iframe = getattr(st, "iframe", None)
    if iframe:
        iframe(html, width=1, height=1)
    else:
        components.html(html, height=1, scrolling=False)
