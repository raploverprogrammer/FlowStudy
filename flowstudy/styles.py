import streamlit as st

from flowstudy.config import (
    LULU_CHAT_SCENE,
    LULU_HOME_SCENE,
    LULU_WELCOME_LANDSCAPE,
    LULU_WELCOME_PORTRAIT,
    static_asset_url,
)


def apply_styles() -> None:
    ocean_background = static_asset_url(LULU_HOME_SCENE)
    welcome_portrait = static_asset_url(LULU_WELCOME_PORTRAIT)
    welcome_landscape = static_asset_url(LULU_WELCOME_LANDSCAPE)
    chat_background = static_asset_url(LULU_CHAT_SCENE)
    st.markdown(
        """
        <style>
        :root {
            --ocean-blue: #70b9d8;
            --ocean-deep: #2d7898;
            --ocean-soft: #eaf7fb;
            --sun-gold: #edb95f;
            --sun-soft: #fff4d8;
            --sand: #fffaf0;
            --ink: #263943;
            --muted: #697b82;
        }
        .stApp {
            background: #fffdf7;
            color: var(--ink);
            position: relative;
        }
        .stApp::before {
            content: "";
            position: fixed;
            inset: 0;
            background:
                linear-gradient(
                    to bottom,
                    rgba(255,253,247,.90) 0%,
                    rgba(255,253,247,.90) 24%,
                    rgba(255,253,247,.85) 58%,
                    rgba(255,253,247,.80) 100%
                ),
                url("__OCEAN_BACKGROUND__") center/cover no-repeat;
            pointer-events: none;
            z-index: 0;
        }
        .stApp:has(.home-background-boost)::before {
            background:
                linear-gradient(
                    to bottom,
                    rgba(255,253,247,.30) 0%,
                    rgba(255,253,247,.30) 52%,
                    rgba(255,253,247,.30) 100%
                ),
                url("__OCEAN_BACKGROUND__") center/cover no-repeat;
        }
        .stApp:has(.welcome-page) {
            background: #fff7ee;
        }
        .stApp:has(.welcome-page) #flowstudy-lulu-pet {
            display: none !important;
        }
        body:has(.welcome-page) #flowstudy-lulu-pet {
            display: none !important;
        }
        .stApp:has(.lulu-chat-page) #flowstudy-lulu-pet,
        body:has(.lulu-chat-page) #flowstudy-lulu-pet {
            display: none !important;
        }
        .stApp:has(.welcome-page)::before {
            background:
                linear-gradient(
                    90deg,
                    rgba(255,247,238,.28) 0%,
                    rgba(255,247,238,.08) 58%,
                    rgba(255,247,238,.02) 100%
                ),
                url("__WELCOME_LANDSCAPE__") center/cover no-repeat;
        }
        .stApp:has(.lulu-chat-page)::before {
            background:
                linear-gradient(
                    to bottom,
                    rgba(255,255,255,.04) 0%,
                    rgba(255,255,255,.02) 100%
                ),
                url("__CHAT_BACKGROUND__") center/100% 100% no-repeat;
        }
        .welcome-page {
            min-height: 0;
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
            width: min(620px, 88vw);
            margin-left: 0;
            margin-right: 0;
            box-sizing: border-box;
            position: relative;
            left: clamp(-120px, -8vw, -48px);
            transform: none;
            padding: 8vh 0 .25rem;
        }
        .welcome-copy {
            padding: 1rem 1.25rem;
            border-radius: 24px;
            background: rgba(255, 252, 247, .76);
            border: 1px solid rgba(255, 255, 255, .8);
            box-shadow: 0 18px 45px rgba(128, 83, 52, .12);
            backdrop-filter: blur(8px);
        }
        .welcome-copy h1 {
            margin: 0;
            color: #684634;
            font-size: clamp(1.9rem, 4.5vw, 2.7rem) !important;
        }
        .welcome-copy p {
            margin: .55rem 0 0;
            color: #896c5a;
            font-size: 1.05rem;
        }
        .stApp:has(.welcome-page) .block-container {
            padding-top: 1rem;
            padding-bottom: .25rem;
        }
        .stApp:has(.welcome-page) [data-testid="stHorizontalBlock"] {
            width: min(620px, 88vw);
            margin: .75rem 0 0 !important;
            gap: 1rem;
            box-sizing: border-box;
            justify-content: center;
            position: relative;
            left: clamp(-120px, -8vw, -48px);
        }
        .stApp:has(.welcome-page) [data-testid="stHorizontalBlock"] div.stButton > button {
            width: 92px;
            height: 92px;
            min-height: 92px;
            padding: .75rem;
            margin: 0 auto;
            border-radius: 50%;
            font-size: .92rem;
            line-height: 1.25;
            white-space: normal;
            border-color: #f1a86f;
            color: #8b5635;
            background: rgba(255, 250, 244, .9);
        }
        .stApp:has(.welcome-page) [data-testid="stHorizontalBlock"] [data-testid="stButton"] {
            display: flex;
            justify-content: center;
        }
        .stApp:has(.welcome-page) [data-testid="stHorizontalBlock"] div.stButton > button[kind="primary"] {
            color: #fff;
            background: linear-gradient(135deg, #f29a55, #edbd68);
            border-color: #ed9a56;
        }
        .stApp:has(.welcome-page) [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:first-child div.stButton > button {
            transform: translateX(-clamp(36px, 7vw, 110px));
        }
        .stApp:has(.welcome-page) [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:last-child div.stButton > button {
            transform: translateX(clamp(36px, 7vw, 110px));
        }
        @media (min-width: 1400px) {
            .stApp:has(.welcome-page) [data-testid="stHorizontalBlock"] {
                transform: none;
            }
        }
        @media (max-width: 700px) {
            .stApp:has(.welcome-page) [data-testid="stHorizontalBlock"] {
                flex-direction: row !important;
                flex-wrap: nowrap !important;
                gap: .5rem !important;
            }
            .stApp:has(.welcome-page) [data-testid="stHorizontalBlock"] div[data-testid="stColumn"] {
                min-width: 0 !important;
                width: calc(50% - .25rem) !important;
                flex: 0 0 calc(50% - .25rem) !important;
            }
            .stApp:has(.welcome-page) [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:first-child div.stButton > button,
            .stApp:has(.welcome-page) [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:last-child div.stButton > button {
                transform: none;
            }
            .stApp:has(.welcome-page)::before {
                background:
                    linear-gradient(
                        to bottom,
                        rgba(255,247,238,.10) 0%,
                        rgba(255,247,238,.02) 72%,
                        rgba(255,247,238,.14) 100%
                    ),
                    url("__WELCOME_PORTRAIT__") center/cover no-repeat;
            }
            .welcome-page {
                min-height: 0;
                width: 92vw;
                justify-content: flex-start;
                margin-left: auto;
                margin-right: auto;
                left: 0;
                padding-top: 30vh;
                padding-bottom: .75rem;
                transform: none;
            }
            .stApp:has(.welcome-page) [data-testid="stHorizontalBlock"] {
                width: 92vw;
                margin-left: auto !important;
                margin-right: auto !important;
                left: 0;
                transform: none;
            }
            .welcome-copy {
                padding: 1rem 1.1rem;
            }
            .welcome-copy h1 { font-size: 2rem !important; }
        }
        .stApp > * { position: relative; z-index: 1; }
        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        [data-testid="stStatusWidget"],
        #MainMenu {
            display: none !important;
        }
        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"] {
            display: none !important;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #eef9fc 0%, #fff8e7 100%);
            border-right: 3px solid #8fcde2;
            box-shadow: 6px 0 24px rgba(55, 127, 157, .08);
        }
        [data-testid="stSidebar"] [role="radiogroup"] label {
            border-radius: 10px;
            padding: .18rem .35rem;
        }
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
            background: #d9f1f8;
            color: #236d8b;
            font-weight: 700;
        }
        .block-container { max-width: 1080px; padding-top: 1.5rem; }
        h1, h2, h3 { letter-spacing: -0.025em; }
        h1 { font-size: 2rem !important; }
        [data-testid="stHeaderActionElements"] {
            display: none !important;
        }
        a[aria-label="Link to heading"] {
            display: none !important;
            visibility: hidden !important;
            pointer-events: none !important;
        }
        .flow-card {
            background: rgba(255,252,245,.94);
            border: 1px solid #f2dfad;
            border-radius: 16px;
            padding: 1.25rem 1.4rem;
            margin: 0.75rem 0 1.25rem;
        }
        .flow-eyebrow {
            color: #737373;
            font-size: 0.82rem;
            font-weight: 600;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }
        .flow-title { font-size: 1.35rem; font-weight: 650; margin: .35rem 0; }
        .flow-muted { color: #686868; }
        div.stButton > button {
            border-radius: 12px;
            font-weight: 600;
            border: 1.5px solid #73bad7;
            background: rgba(255,255,255,.9);
            color: #265f77;
        }
        div.stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #4fa9cc, #73c1dc);
            border-color: #4fa9cc;
            color: white;
            box-shadow: 0 8px 18px rgba(56, 139, 174, .18);
        }
        [class*="st-key-page_back_"] {
            margin: 0 0 .35rem;
            position: relative;
            z-index: 20;
        }
        [class*="st-key-page_back_"] div.stButton > button {
            width: 34px !important;
            min-width: 34px !important;
            height: 34px !important;
            min-height: 34px !important;
            padding: 0 !important;
            border-radius: 50% !important;
            font-size: 1.25rem !important;
            line-height: 1 !important;
            font-weight: 500 !important;
            color: #286b83 !important;
            background: rgba(255,255,255,.82) !important;
            box-shadow: 0 3px 10px rgba(56,139,174,.12) !important;
        }
        [class*="st-key-page_back_"] div.stButton > button:hover {
            background: rgba(255,255,255,.98) !important;
            border-color: #4fa9cc !important;
        }
        [data-testid="stMetric"] {
            background: linear-gradient(145deg, rgba(255,255,255,.96), rgba(243,251,243,.94));
            border: 2px solid #8fd3a0;
            border-radius: 16px;
            padding: 1rem;
            box-sizing: border-box;
        }
        [data-testid="stExpander"] {
            background: rgba(255,252,245,.95);
            border: 2px solid #ffc75c !important;
            border-radius: 14px !important;
            overflow: hidden;
            box-sizing: border-box;
        }
        [data-testid="stExpander"] details,
        [data-testid="stExpander"] summary,
        [data-testid="stExpander"] [data-testid="stVerticalBlock"] {
            background: rgba(255,252,245,.96) !important;
        }
        [data-testid="stDataFrame"] {
            background: rgba(255,255,255,.96);
            border: 2px solid #79c8e4;
            border-radius: 14px;
            overflow: hidden;
            box-sizing: border-box;
        }
        [data-testid="stDataFrame"] > div {
            background: rgba(255,255,255,.96) !important;
        }
        [data-testid="stVerticalBlockBorderWrapper"] {
            border: 2px solid #89c9de !important;
            background: rgba(255, 254, 249, .95);
            border-radius: 16px;
            box-sizing: border-box;
        }
        [data-testid="stVerticalBlockBorderWrapper"] > div {
            border-radius: 14px;
            background: rgba(255, 254, 249, .95);
        }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.st-key-resume_learning_card) {
            background: rgba(255,253,248,.96);
            border: 3px solid #55b9f3 !important;
            box-shadow: 0 6px 18px rgba(72, 161, 214, .10);
        }
        [data-testid="stVerticalBlockBorderWrapper"]:has([class*="st-key-favorite_card_"]) {
            background: rgba(255,253,248,.96);
            border: 3px solid #ad7de2 !important;
            box-shadow: 0 6px 18px rgba(143, 100, 199, .09);
        }
        [data-testid="stChatMessage"] {
            border-radius: 16px;
            border: 2px solid #a4d7e7;
            background: rgba(247, 253, 255, .96);
        }
        [data-testid="stBottom"],
        [data-testid="stBottom"] > div,
        [data-testid="stChatInput"] {
            background:
                linear-gradient(rgba(255,253,247,.80), rgba(255,253,247,.80)),
                url("__OCEAN_BACKGROUND__") center bottom/cover no-repeat !important;
        }
        [data-testid="stBottom"] {
            border-top: 1px solid rgba(112,185,216,.22);
            box-shadow: 0 -8px 24px rgba(54,111,136,.05);
        }
        [data-testid="stChatInput"] > div,
        [data-testid="stChatInput"] form,
        [data-testid="stChatInput"] [data-baseweb="textarea"],
        [data-testid="stChatInput"] textarea,
        [data-testid="stChatInput"] button {
            background: #fff4cf !important;
        }
        [data-testid="stChatInput"] [data-baseweb="textarea"],
        [data-testid="stChatInput"] textarea {
            border-radius: 999px 0 0 999px !important;
        }
        [data-testid="stChatInput"] button {
            border-radius: 0 999px 999px 0 !important;
        }
        .stApp:has(.lulu-chat-page) .block-container {
            max-width: none !important;
            width: 100% !important;
            margin: 0 !important;
            padding: 0 0 5rem !important;
        }
        .stApp:has(.lulu-chat-page) h2 {
            color: #1f2d33;
            text-shadow: 0 1px 10px rgba(255,255,255,.78);
        }
        .stApp:has(.lulu-chat-page) [data-testid="stChatMessage"] {
            display: flex;
            align-items: flex-end;
            gap: .55rem;
            width: 100%;
            max-width: none;
            box-sizing: border-box;
            border: 0;
            background: transparent;
            padding: .25rem 1rem;
            margin: 0;
            /* An expanded question image must be painted immediately. The
               previous content-visibility optimization could leave it blank
               until the browser performed another layout pass. */
            content-visibility: visible;
        }
        .stApp:has(.lulu-chat-page) [data-testid="stChatMessage"] > img {
            position: relative;
            z-index: 2;
            width: 38px;
            height: 38px;
            flex: 0 0 38px;
            border-radius: 6px;
            object-fit: cover;
            border: 2px solid rgba(255,255,255,.9);
            box-shadow: 0 2px 8px rgba(0,0,0,.16);
        }
        .stApp:has(.lulu-chat-page) [data-testid="stChatMessageContent"] {
            display: inline-block;
            flex: 0 1 auto !important;
            width: fit-content !important;
            max-width: min(78vw, 720px) !important;
            min-width: 0 !important;
            margin: 0 !important;
            padding: .65rem .85rem;
            border-radius: 6px 16px 16px 16px;
            background: rgba(255,255,255,.92);
            box-shadow: 0 2px 8px rgba(0,0,0,.08);
        }
        .stApp:has(.lulu-chat-page) [data-testid="stChatMessageContent"] img {
            display: block;
            max-width: 100%;
            height: auto;
        }
        .stApp:has(.lulu-chat-page) [class*="st-key-lulu_question_viewer"] {
            margin-top: .55rem;
            padding: .55rem;
            border: 1px solid rgba(112,185,216,.55);
            border-radius: 10px;
            background: rgba(255,255,255,.72);
        }
        .stApp:has(.lulu-chat-page) [data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) {
            flex-direction: row-reverse;
        }
        .stApp:has(.lulu-chat-page) [data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) [data-testid="stChatMessageContent"] {
            border-radius: 16px 6px 16px 16px;
            background: rgba(149,236,105,.95);
        }
        .stApp:has(.lulu-chat-page) .lulu-progress {
            color: #55717b;
            font-size: .92rem;
            font-style: italic;
        }
        .stApp:has(.lulu-chat-page) .lulu-question-details {
            margin-top: .55rem;
            border: 1px solid rgba(112,185,216,.55);
            border-radius: 10px;
            overflow: hidden;
            background: rgba(255,255,255,.72);
        }
        .stApp:has(.lulu-chat-page) .lulu-question-details summary {
            cursor: pointer;
            padding: .48rem .7rem;
            color: #266b83;
            font-weight: 600;
            list-style-position: inside;
        }
        .stApp:has(.lulu-chat-page) .lulu-question-details img {
            display: block;
            width: 100%;
            height: auto;
            padding: .35rem;
            box-sizing: border-box;
        }
        .stApp:has(.lulu-chat-page) [data-testid="stBottom"] {
            background: transparent !important;
            border-top: 0 !important;
            box-shadow: none;
            backdrop-filter: none;
        }
        .stApp:has(.lulu-chat-page) [data-testid="stBottom"] > div,
        .stApp:has(.lulu-chat-page) [data-testid="stChatInput"] {
            background: transparent !important;
        }
        .stApp:has(.lulu-chat-page) [data-testid="stChatInput"] {
            max-width: 860px;
            width: calc(100% - 2rem);
            margin: .35rem auto .6rem;
            /* Keep the composer inside the mobile safe area. */
            transform: none !important;
        }
        .stApp:has(.lulu-chat-page) [data-testid="stChatInput"] > div,
        .stApp:has(.lulu-chat-page) [data-testid="stChatInput"] form {
            background: rgba(255,244,207,.96) !important;
            border: 1px solid rgba(255,255,255,.82) !important;
            border-radius: 999px !important;
            box-shadow: 0 3px 14px rgba(37,38,45,.16) !important;
        }
        .stApp:has(.lulu-chat-page) [data-testid="stChatInput"] [data-baseweb="textarea"],
        .stApp:has(.lulu-chat-page) [data-testid="stChatInput"] textarea {
            min-height: 42px !important;
            max-height: 42px !important;
            overflow: hidden !important;
            border: 0 !important;
            border-radius: 999px 0 0 999px !important;
            background: transparent !important;
            box-shadow: none !important;
        }
        .stApp:has(.lulu-chat-page) [data-testid="stChatInput"] button {
            border: 0 !important;
            border-radius: 0 999px 999px 0 !important;
            background: transparent !important;
            box-shadow: none !important;
        }
        [data-testid="stTextInputRootElement"],
        [data-baseweb="select"] > div,
        [data-testid="stTextArea"] textarea {
            border: 1.5px solid #e9ad51 !important;
            border-radius: 10px !important;
        }
        [data-testid="stCheckbox"] label,
        [data-testid="stRadio"] label {
            border-color: #f0b85f;
        }
        .lulu-note {
            background: rgba(255,244,199,.58);
            border: 2px solid #f2ca4d;
            border-radius: 14px;
            padding: 1rem 1.1rem;
            margin: 0.6rem 0 1rem;
            color: #5d471b;
            line-height: 1.75;
        }
        [class*="st-key-ocean_hero_"] {
            min-height: 350px;
            background-size: cover;
            background-position: center;
            border: 2px solid #9fd3e5;
            border-radius: 26px;
            padding: 2.4rem 2.25rem;
            margin: .35rem 0 1.35rem;
            box-shadow: 0 14px 38px rgba(52, 119, 147, .12);
            overflow: hidden;
            box-sizing: border-box;
        }
        .ocean-hero-copy {
            min-height: 210px;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        .ocean-kicker {
            width: fit-content;
            padding: .35rem .7rem;
            border-radius: 999px;
            background: rgba(225, 245, 251, .92);
            color: #26708e;
            font-weight: 750;
            font-size: .82rem;
            margin-bottom: .8rem;
        }
        .ocean-hero-copy h1 {
            color: #234d60;
            font-size: 2.25rem !important;
            line-height: 1.2;
            margin: 0 0 .75rem;
        }
        .ocean-hero-copy p {
            color: #526c77;
            font-size: 1.05rem;
            line-height: 1.8;
            margin: 0;
        }
        .home-hero {
            padding: .35rem 0 .5rem;
        }
        .home-hero-title {
            font-size: 2rem;
            line-height: 1.2;
            font-weight: 750;
            margin-bottom: .55rem;
        }
        .home-hero-subtitle {
            font-size: 1.12rem;
            line-height: 1.8;
            color: #4f493f;
        }
        .home-hero-memory {
            margin-top: .55rem;
            color: #81786d;
            font-size: .92rem;
        }
        .page-banner {
            border-radius: 20px;
            padding: 1.25rem 1.4rem;
            margin: .65rem 0 1.3rem;
            border: 2px solid;
            box-sizing: border-box;
            overflow: visible;
        }
        .page-banner h1 {
            margin: 0 0 .35rem;
            font-size: 2rem;
        }
        .page-banner p {
            margin: 0;
            color: #696158;
            line-height: 1.65;
        }
        .page-blue {
            background: rgba(234,245,255,.52);
            border-color: #65baf0;
        }
        .page-orange {
            background: rgba(255,240,220,.52);
            border-color: #ffa936;
        }
        .page-green {
            background: rgba(234,247,233,.52);
            border-color: #6fcb84;
        }
        .page-purple {
            background: rgba(243,237,255,.52);
            border-color: #ad82eb;
        }
        .warm-card {
            border-radius: 20px;
            padding: 1.35rem 1.45rem;
            margin: .7rem 0 1rem;
            border: 2px solid;
            box-sizing: border-box;
        }
        .recommend-card { background: rgba(255,243,217,.56); border-color: #e9b85e; }
        .growth-card { background: rgba(233,247,247,.56); border-color: #74bfd0; }
        .insight-card { background: rgba(237,246,255,.56); border-color: #83bfdf; }
        .reward-card { background: rgba(255,245,201,.58); border-color: #edc94e; }
        .warm-card-label {
            font-size: .82rem;
            color: #756d62;
            font-weight: 700;
            margin-bottom: .45rem;
        }
        .warm-card-title {
            font-size: 1.35rem;
            font-weight: 750;
            margin-bottom: .4rem;
        }
        .warm-card-copy {
            font-size: 1.02rem;
            line-height: 1.75;
            color: #4e473d;
        }
        .mastery-number {
            font-size: 2.6rem;
            font-weight: 780;
            color: #347451;
            line-height: 1;
            margin: .35rem 0 .8rem;
        }
        .voyager-rank {
            font-size: 2rem;
            font-weight: 780;
            color: #286e86;
            line-height: 1.25;
            margin: .3rem 0 .65rem;
        }
        .level-grid {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: .55rem;
            margin-top: .9rem;
        }
        .level-pill {
            background: rgba(255,255,255,.68);
            border: 1.5px solid #91cede;
            border-radius: 12px;
            padding: .7rem .45rem;
            text-align: center;
            color: #416773;
            font-weight: 650;
        }
        .mentor-item {
            padding: .95rem 0;
            border-bottom: 1px solid rgba(98, 79, 51, .12);
        }
        .mentor-item:last-child { border-bottom: 0; }
        .mentor-rank { font-size: 1.15rem; margin-right: .35rem; }
        .mentor-title { font-weight: 720; font-size: 1.05rem; }
        .mentor-reason { color: #756d62; margin: .25rem 0 0 1.9rem; }
        @media (max-width: 640px) {
            .level-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            [class*="st-key-ocean_hero_"] {
                min-height: 390px;
                padding: 1.4rem;
                background-position: 62% center;
            }
            .ocean-hero-copy h1 { font-size: 1.75rem !important; }
        }
        </style>
        """.replace("__OCEAN_BACKGROUND__", ocean_background)
        .replace("__WELCOME_PORTRAIT__", welcome_portrait)
        .replace("__WELCOME_LANDSCAPE__", welcome_landscape)
        .replace("__CHAT_BACKGROUND__", chat_background),
        unsafe_allow_html=True,
    )
