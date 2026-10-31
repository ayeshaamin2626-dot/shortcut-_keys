"""Shortcut Finder: find keyboard shortcuts for any computer or app, powered by Gemini."""

import json
import os
import re

import streamlit as st
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
# Models are tried in order. If the first one is unavailable for your key,
# the next one is used. You can override the first model with the MODEL_NAME
# secret or environment variable.
DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash"]

OPERATING_SYSTEMS = ["Windows", "macOS", "Linux", "ChromeOS"]

POPULAR_APPS = [
    "Operating system (general)",
    "Google Chrome",
    "Microsoft Word",
    "Microsoft Excel",
    "Microsoft PowerPoint",
    "Visual Studio Code",
    "Gmail",
    "Google Docs",
    "Zoom",
    "Slack",
    "File Explorer / Finder",
    "Terminal / Command Prompt",
    "Other (type below)",
]

MAX_INPUT_CHARS = 100

SYSTEM_INSTRUCTION = (
    "You are an expert on computer keyboard shortcuts. "
    "Give only shortcuts that really exist for the given operating system and "
    "application. Never invent a shortcut; if you are unsure, leave it out. "
    "Write keys the way the platform labels them (Ctrl, Alt, Shift, Win, Cmd, "
    "Option) and join them with ' + '. "
    "If the request is not about keyboard shortcuts, return an empty list and "
    "explain briefly in 'note'."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_secret(name):
    """Read a value from Streamlit secrets or environment variables."""
    try:
        value = st.secrets.get(name)
    except Exception:  # no secrets file, which is fine
        value = None
    return value or os.environ.get(name)


def get_api_key():
    return get_secret("GEMINI_API_KEY") or get_secret("GOOGLE_API_KEY")


def build_prompt(os_name, app_name, task, count):
    prompt = (
        f"Operating system: {os_name}\n"
        f"Application: {app_name}\n"
    )
    if task:
        prompt += f"The user wants to: {task}\n"
        prompt += f"List up to {count} most relevant shortcuts for this goal.\n"
    else:
        prompt += f"List the {count} most useful shortcuts, grouped by category.\n"
    prompt += (
        "Return JSON in this exact shape: "
        '{"shortcuts": [{"action": "...", "keys": "...", "category": "..."}], '
        '"note": "optional short tip or warning"}'
    )
    return prompt


def parse_response(text):
    """Turn the model's JSON text into (rows, note). Tolerates code fences."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    data = json.loads(text)
    if isinstance(data, list):  # model returned a bare list
        data = {"shortcuts": data}

    rows = []
    for item in data.get("shortcuts", []):
        if not isinstance(item, dict):
            continue
        action = str(item.get("action", "")).strip()
        keys = str(item.get("keys", "")).strip()
        if action and keys:
            rows.append(
                {
                    "Action": action,
                    "Shortcut": keys,
                    "Category": str(item.get("category", "General")).strip() or "General",
                }
            )
    return rows, str(data.get("note", "") or "").strip()


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_shortcuts(api_key, models, os_name, app_name, task, count):
    """Ask Gemini for shortcuts. Cached for an hour so repeat searches are free."""
    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        temperature=0.2,
    )
    prompt = build_prompt(os_name, app_name, task, count)

    last_error = None
    for model in models:
        try:
            response = client.models.generate_content(
                model=model, contents=prompt, config=config
            )
            return parse_response(response.text)
        except json.JSONDecodeError as err:
            last_error = err  # bad JSON: try the next model
        except Exception as err:  # noqa: BLE001
            message = str(err)
            # Only fall through to the next model if this one was not found.
            if "404" in message or "NOT_FOUND" in message.upper():
                last_error = err
                continue
            raise
    raise last_error or RuntimeError("No model could answer.")


def friendly_error(err):
    message = str(err)
    upper = message.upper()
    if "API_KEY" in upper or "API KEY" in upper or "PERMISSION_DENIED" in upper or "401" in message or "403" in message:
        return "Your Gemini API key was rejected. Please check it and try again."
    if "429" in message or "RESOURCE_EXHAUSTED" in upper or "QUOTA" in upper:
        return "The Gemini free limit was reached. Please wait a minute and try again."
    if isinstance(err, json.JSONDecodeError):
        return "The AI sent an answer in an unexpected format. Please press the button again."
    return f"Something went wrong while asking Gemini: {message[:200]}"


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Shortcut Finder", page_icon="⌨️", layout="centered")

st.title("⌨️ Shortcut Finder")
st.caption("Find keyboard shortcuts for any computer or app. Powered by Gemini.")

api_key = get_api_key()
with st.sidebar:
    st.header("Settings")
    if not api_key:
        api_key = st.text_input(
            "Gemini API key",
            type="password",
            help="Get a free key at https://aistudio.google.com/apikey",
        )
    else:
        st.success("API key loaded", icon="🔑")
    count = st.slider("Number of shortcuts", min_value=5, max_value=30, value=15, step=5)
    st.markdown(
        "Shortcuts are written by AI. Always double-check important ones "
        "in the app's own help menu."
    )

models = tuple(
    [m for m in [get_secret("MODEL_NAME")] if m]
    + [m for m in DEFAULT_MODELS if m != get_secret("MODEL_NAME")]
)

with st.form("search_form"):
    col1, col2 = st.columns(2)
    os_name = col1.selectbox("Your computer", OPERATING_SYSTEMS)
    app_choice = col2.selectbox("Program", POPULAR_APPS)
    custom_app = st.text_input(
        "Other program",
        placeholder="e.g. Photoshop, AutoCAD, Notepad++",
        max_chars=MAX_INPUT_CHARS,
        help="Only used when you choose 'Other (type below)'.",
    )
    task = st.text_input(
        "What do you want to do? (optional)",
        placeholder="e.g. take a screenshot, switch windows, select all",
        max_chars=MAX_INPUT_CHARS,
    )
    submitted = st.form_submit_button("Find shortcuts", type="primary")

if submitted:
    app_name = custom_app.strip() if app_choice.startswith("Other") else app_choice
    if not api_key:
        st.error("Please add your Gemini API key in the sidebar first.")
    elif not app_name:
        st.error("Please type the name of the program you want shortcuts for.")
    else:
        try:
            with st.spinner("Looking up shortcuts..."):
                rows, note = fetch_shortcuts(
                    api_key, models, os_name, app_name, task.strip(), count
                )
            st.session_state["result"] = {
                "rows": rows,
                "note": note,
                "title": f"{app_name} on {os_name}",
            }
        except Exception as err:  # noqa: BLE001
            st.session_state.pop("result", None)
            st.error(friendly_error(err))

result = st.session_state.get("result")
if result:
    st.subheader(result["title"])
    if not result["rows"]:
        st.info(result["note"] or "No shortcuts found. Try a different program or wording.")
    else:
        query = st.text_input("Filter results", placeholder="Type to filter...")
        rows = [
            r
            for r in result["rows"]
            if query.lower() in " ".join(r.values()).lower()
        ]
        if not rows:
            st.warning("Nothing matches your filter.")
        for category in dict.fromkeys(r["Category"] for r in rows):
            st.markdown(f"**{category}**")
            st.table(
                [
                    {"Action": r["Action"], "Shortcut": r["Shortcut"]}
                    for r in rows
                    if r["Category"] == category
                ]
            )
        if result["note"]:
            st.caption(f"💡 {result['note']}")
        csv = "Category,Action,Shortcut\n" + "\n".join(
            '"{}","{}","{}"'.format(
                r["Category"].replace('"', '""'),
                r["Action"].replace('"', '""'),
                r["Shortcut"].replace('"', '""'),
            )
            for r in result["rows"]
        )
        st.download_button("Download as CSV", csv, file_name="shortcuts.csv", mime="text/csv")
