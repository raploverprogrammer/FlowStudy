import streamlit as st

from flowstudy.config import LULU_HOME_SCENE


@st.cache_data(show_spinner=False)
def _ocean_background_data() -> str:
    import base64

    return base64.b64encode(LULU_HOME_SCENE.read_bytes()).decode("ascii")


def apply_styles() -> None:
    ocean_background = _ocean_background_data()
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
                url("data:image/webp;base64,__OCEAN_BACKGROUND__") center/cover no-repeat;
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
                url("data:image/webp;base64,__OCEAN_BACKGROUND__") center/cover no-repeat;
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
                url("data:image/png;base64,__OCEAN_BACKGROUND__") center bottom/cover no-repeat !important;
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
        """.replace("__OCEAN_BACKGROUND__", ocean_background),
        unsafe_allow_html=True,
    )
