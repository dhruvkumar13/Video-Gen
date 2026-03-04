"""
Streamlit Math Tutor Video Generator.

Streamlit-native frontend for the math tutoring video pipeline.
Replaces server.py's Flask+HTML UI while reusing all backend modules.
"""
import streamlit as st

# MUST be first Streamlit command
st.set_page_config(page_title="Math Tutor", page_icon="\U0001f4d0", layout="wide")

import json
import os
import uuid
import shutil
import threading
import time
import logging
import platform
from datetime import datetime

# ── Bridge Streamlit secrets → env vars (for backend modules) ────
try:
    for _key in ("OPENAI_API_KEY", "ELEVEN_API_KEY", "MEM0_API_KEY"):
        if _key not in os.environ:
            _val = st.secrets.get(_key, "")
            if _val:
                os.environ[_key] = _val
except FileNotFoundError:
    pass  # No secrets.toml — use .env or existing env vars instead

from dotenv import load_dotenv
load_dotenv()

# ── Fix paths for Linux (Streamlit Cloud) ────────────────────────
import tts
import merge_audio
if platform.system() != "Darwin":
    _ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    _ffprobe = shutil.which("ffprobe") or "ffprobe"
    tts.FFPROBE = _ffprobe
    tts.FFMPEG = _ffmpeg
    merge_audio.FFMPEG = _ffmpeg
    merge_audio.FFPROBE = _ffprobe

from openai import OpenAI
from ai_solver import generate_solution, TUTOR_PERSONALITY
from generate import render_job
from tts import generate_narration
from merge_audio import merge_video_audio
from memory import (
    add_preference,
    get_preferences,
    clear_preferences,
    PREFERENCE_OPTIONS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

JOBS_DIR = "jobs"
os.makedirs(JOBS_DIR, exist_ok=True)

# ── Chat system prompt (same as server.py) ───────────────────────
CHAT_SYSTEM_PROMPT = TUTOR_PERSONALITY + """

YOUR ROLE IN THIS CHAT:
You are helping a Calculus 1 student formulate their question for an animated video lesson.
Your goal is to understand exactly what problem they want solved and how they'd like it explained.

Chat-specific guidelines:
- Be concise (2-3 sentences per reply) since this is a chat, not a lecture.
- If the question is already specific (e.g. "find the derivative of x^3 + 2x"),
  confirm it and mark ready immediately.
- If vague (e.g. "help with derivatives"), ask 1-2 short clarifying questions
  about the function, technique, or specific part they need help with.
- When you have a clear, solvable Calculus 1 question, restate the question
  and add [READY] at the very end of your message.

MULTI-VIDEO CONVERSATIONS:
The student can generate MULTIPLE videos in the same chat session. After a video
is generated, they may:
- Ask a follow-up ("now show me the integral of that")
- Ask a completely new problem ("what about the derivative of ln(x)?")
- Ask for a variation ("can you redo that but with chain rule instead?")

When you see a new question after a previous [READY], treat it as a fresh request.
Confirm the new question and add [READY] again. Each [READY] triggers a separate
video. Keep the conversation flowing naturally.

Examples:
User: "derivatives"
→ "Sure! What function would you like to differentiate?"

User: "find the derivative of sin(x) * e^x"
→ "Great! I'll create a video showing how to differentiate sin(x)·eˣ using the product rule. Click Generate when you're ready! [READY]"

IMPORTANT: Add [READY] only when you have enough information. The [READY] tag is hidden from the student."""

# Memory extraction prompt
_MEMORY_EXTRACT_PROMPT = """\
You are a memory extraction agent for a math tutoring app. Given the student's \
latest message (and recent chat context), extract 1-4 truly useful facts about \
the student (hobbies, learning style, emotional state, math strengths/weaknesses). \
Return ONLY a short bullet list (one per line, starting with "- "). \
If there's nothing meaningful to extract, return exactly: NONE"""


# ── Cached OpenAI client ─────────────────────────────────────────
@st.cache_resource
def _get_oai():
    return OpenAI()


# ── Session state defaults ───────────────────────────────────────
_DEFAULTS = {
    "student_name": "",
    "student_id": "",
    "name_submitted": False,
    "messages": [],
    "ready": False,
    "final_question": "",
    "last_generate_idx": 0,
    "generating": False,
    "job_id": None,
    "job_status": {"status": "idle", "step": "", "progress": 0},
    "completed_job_id": None,
    "active_prefs": set(),
    "playback_job_id": None,
}

for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── Helper functions ─────────────────────────────────────────────

def _chat_reply(messages, student_memory=""):
    """Get a chat response from GPT."""
    oai = _get_oai()
    system = CHAT_SYSTEM_PROMPT
    if student_memory:
        system += "\n\nStudent memories:\n" + student_memory
    gpt_msgs = [{"role": "system", "content": system}]
    for m in messages:
        gpt_msgs.append({"role": m["role"], "content": m["content"]})
    response = oai.chat.completions.create(
        model="gpt-5.3-chat-latest",
        max_completion_tokens=256,
        messages=gpt_msgs,
    )
    return response.choices[0].message.content


def _extract_question(messages, start_idx=0):
    """Build a solver-ready question from chat messages."""
    user_msgs = [m["content"] for m in messages[start_idx:] if m["role"] == "user"]
    if not user_msgs:
        return ""
    if len(user_msgs) == 1:
        return user_msgs[0]
    return "Context: " + " → ".join(user_msgs)


def _extract_and_store_memories(message, recent_messages, student_id):
    """Background task: extract personal facts and store in mem0."""
    try:
        oai = _get_oai()
        context_msgs = [{"role": "system", "content": _MEMORY_EXTRACT_PROMPT}]
        for m in recent_messages[-4:]:
            context_msgs.append({"role": m["role"], "content": m["content"]})
        resp = oai.chat.completions.create(
            model="gpt-4.1-nano",
            max_completion_tokens=250,
            messages=context_msgs,
        )
        extraction = resp.choices[0].message.content.strip()
        if extraction and extraction.upper() != "NONE":
            for line in extraction.split("\n"):
                line = line.strip().lstrip("- ").strip()
                if line and len(line) > 3:
                    add_preference(line, user_id=student_id)
    except Exception as e:
        logging.warning("Memory extraction failed: %s", e)


def _update_status(job_id, status, step, progress, error=None):
    """Write status to disk (for library) and session state (for live UI)."""
    path = os.path.join(JOBS_DIR, job_id, "status.json")
    data = {"status": status, "step": step, "progress": progress}
    if error:
        data["error"] = error
    with open(path, "w") as f:
        json.dump(data, f)
    st.session_state.job_status = data


def _get_video_path(job_id):
    """Find the video file for a job."""
    final = os.path.join(JOBS_DIR, job_id, "final.mp4")
    if os.path.isfile(final) and os.path.getsize(final) > 0:
        return final
    raw = os.path.join(JOBS_DIR, job_id, "media", "videos", "scene", "720p30", "TutorialScene.mp4")
    if os.path.isfile(raw) and os.path.getsize(raw) > 0:
        return raw
    return None


def _load_library():
    """Scan jobs/ for completed videos."""
    videos = []
    if not os.path.isdir(JOBS_DIR):
        return videos
    for entry in os.listdir(JOBS_DIR):
        job_dir = os.path.join(JOBS_DIR, entry)
        if not os.path.isdir(job_dir):
            continue
        status_path = os.path.join(job_dir, "status.json")
        if not os.path.isfile(status_path):
            continue
        try:
            with open(status_path) as f:
                sd = json.load(f)
            if sd.get("status") != "complete":
                continue
        except Exception:
            continue
        if not _get_video_path(entry):
            continue
        title = "Untitled"
        q_path = os.path.join(job_dir, "question.json")
        if os.path.isfile(q_path):
            try:
                with open(q_path) as f:
                    title = json.load(f).get("title", "Untitled")
            except Exception:
                pass
        created = os.path.getmtime(status_path)
        videos.append({"job_id": entry, "title": title, "created_at": created})
    videos.sort(key=lambda v: v["created_at"], reverse=True)
    return videos


# ── Video generation pipeline (runs in background thread) ────────

def _run_pipeline(job_id, question_text, student_id, chat_history):
    """Background pipeline: AI solve → TTS → Manim render → merge."""
    job_dir = os.path.join(JOBS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    try:
        # Load student preferences
        prefs = get_preferences(user_id=student_id)

        # Build chat context
        chat_context = ""
        if chat_history:
            recent = chat_history[-8:]
            lines = []
            for m in recent:
                role = "Student" if m.get("role") == "user" else "Tutor"
                lines.append(f"{role}: {m['content']}")
            if lines:
                chat_context = "Recent conversation:\n" + "\n".join(lines)

        # Step 1: AI solver (0% → 20%)
        def _progress_cb(stage):
            if stage == "coach":
                _update_status(job_id, "solving", "Tutor is planning the lesson...", 8)
            elif stage == "coach_done":
                _update_status(job_id, "solving", "Converting to animation format...", 15)
            elif stage == "producer_done":
                _update_status(job_id, "solving", "Solution ready!", 20)

        _update_status(job_id, "solving", "Tutor is planning the lesson...", 5)
        solution = generate_solution(
            question_text, preferences=prefs,
            chat_context=chat_context, progress_cb=_progress_cb,
        )

        with open(os.path.join(job_dir, "question.json"), "w") as f:
            json.dump(solution, f, indent=2)

        # Step 2: TTS narration (20% → 40%)
        _update_status(job_id, "narrating", "Generating voice narration...", 25)
        audio_path, step_durations = generate_narration(solution, job_dir)

        # Write durations into question.json for renderer timing
        if step_durations:
            for idx, dur in step_durations.items():
                if idx < len(solution["steps"]):
                    solution["steps"][idx]["narration_duration"] = round(dur, 2)
            with open(os.path.join(job_dir, "question.json"), "w") as f:
                json.dump(solution, f, indent=2)

        # Step 3: Render with Manim (40% → 70%)
        abs_job_dir = os.path.abspath(job_dir)
        _update_status(job_id, "rendering", "Rendering video with Manim...", 45)
        video_path = render_job(abs_job_dir)

        # Step 4: Merge video + narration + music (70% → 90%)
        if audio_path and os.path.isfile(audio_path):
            _update_status(job_id, "merging", "Adding narration to video...", 80)
            final_path = os.path.join(job_dir, "final.mp4")
            merge_video_audio(video_path, audio_path, final_path)

        # Done
        _update_status(job_id, "complete", "Video ready!", 100)
        st.session_state.completed_job_id = job_id
        st.session_state.generating = False

    except Exception as e:
        logging.error("Pipeline error for %s: %s", job_id, e, exc_info=True)
        _update_status(job_id, "error", f"Error: {e}", -1, error=str(e))
        st.session_state.generating = False


# ── Name prompt ──────────────────────────────────────────────────

if not st.session_state.name_submitted:
    st.markdown(
        "<h1 style='text-align:center; margin-top:15vh;'>📐 Math Tutor</h1>"
        "<p style='text-align:center; color:#64748b;'>AI-powered animated video lessons for Calculus</p>",
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("name_form"):
            name = st.text_input("What's your name?", placeholder="Your first name...")
            submitted = st.form_submit_button("Get Started", type="primary", use_container_width=True)
            if submitted and name.strip():
                st.session_state.student_name = name.strip()
                st.session_state.student_id = name.strip().lower().replace(" ", "_")
                st.session_state.name_submitted = True
                # Initialize chat with welcome message
                st.session_state.messages = [{
                    "role": "assistant",
                    "content": f"Hi {name.strip()}! I'm your math tutor. What Calculus topic would you like a video lesson on?",
                }]
                st.rerun()
    st.stop()


# ── Sidebar: Preferences + Library ───────────────────────────────

with st.sidebar:
    st.markdown(f"**{st.session_state.student_name}**")

    # New chat button
    if st.button("+ New Chat", use_container_width=True):
        name = st.session_state.student_name
        st.session_state.messages = [{
            "role": "assistant",
            "content": f"Hi {name}! What would you like to learn next?",
        }]
        st.session_state.ready = False
        st.session_state.final_question = ""
        st.session_state.generating = False
        st.session_state.completed_job_id = None
        st.session_state.playback_job_id = None
        st.session_state.last_generate_idx = 0
        st.rerun()

    st.divider()

    # Preferences
    st.subheader("Preferences")
    pref_labels = {
        "more_graphs": "📊 More Graphs",
        "more_steps": "🔍 More Detail",
        "simpler": "💬 Simpler Language",
        "more_color": "🎨 Color-Coded",
        "more_examples": "📝 More Examples",
        "concise": "✂️ Concise",
        "more_diagrams": "📐 More Diagrams",
    }
    for key, label in pref_labels.items():
        is_active = key in st.session_state.active_prefs
        if st.toggle(label, value=is_active, key=f"pref_{key}"):
            if key not in st.session_state.active_prefs:
                st.session_state.active_prefs.add(key)
                desc = PREFERENCE_OPTIONS.get(key, key)
                add_preference(desc, user_id=st.session_state.student_id)
        else:
            st.session_state.active_prefs.discard(key)

    if st.button("Reset All", type="secondary"):
        clear_preferences(user_id=st.session_state.student_id)
        st.session_state.active_prefs = set()
        st.rerun()

    st.divider()

    # Video Library
    st.subheader("Video Library")
    library = _load_library()
    if not library:
        st.caption("No videos yet. Generate one!")
    for vid in library:
        if st.button(f"▶ {vid['title']}", key=f"lib_{vid['job_id']}", use_container_width=True):
            st.session_state.playback_job_id = vid["job_id"]
            st.rerun()


# ── Main area ────────────────────────────────────────────────────

st.markdown(
    "<h2 style='margin-bottom:0'>📐 Math Tutor</h2>"
    "<p style='color:#64748b; margin-top:0'>Ask a Calculus question, then generate an animated video lesson</p>",
    unsafe_allow_html=True,
)

# Library playback mode
if st.session_state.playback_job_id:
    job_id = st.session_state.playback_job_id
    vpath = _get_video_path(job_id)
    if vpath:
        st.video(vpath)
    else:
        st.error("Video file not found.")
    if st.button("Back to chat"):
        st.session_state.playback_job_id = None
        st.rerun()
    st.stop()

# Display chat messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        # Strip [READY] from display
        text = msg["content"].replace("[READY]", "").strip()
        st.write(text)

# Sample question chips (only when just the welcome message exists)
if len(st.session_state.messages) == 1 and not st.session_state.generating:
    samples = [
        "Find the derivative of x⁴ - 3x² + 5",
        "Evaluate lim(x→3) of (x²-9)/(x-3)",
        "Find ∫(4x³ + 2x) dx",
    ]
    cols = st.columns(len(samples))
    for i, sample in enumerate(samples):
        if cols[i].button(sample, key=f"sample_{i}"):
            st.session_state.messages.append({"role": "user", "content": sample})
            st.rerun()

# Generate video button
if st.session_state.ready and not st.session_state.generating and not st.session_state.completed_job_id:
    if st.button("🎬 Generate Video", type="primary", use_container_width=True):
        job_id = str(uuid.uuid4())
        job_dir = os.path.join(JOBS_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)

        st.session_state.job_id = job_id
        st.session_state.generating = True
        st.session_state.completed_job_id = None
        st.session_state.job_status = {"status": "queued", "step": "Starting...", "progress": 0}

        question_text = _extract_question(
            st.session_state.messages,
            start_idx=st.session_state.last_generate_idx,
        )
        st.session_state.last_generate_idx = len(st.session_state.messages)

        thread = threading.Thread(
            target=_run_pipeline,
            args=(job_id, question_text, st.session_state.student_id, list(st.session_state.messages)),
            daemon=True,
        )
        thread.start()
        st.rerun()

# Progress display during generation
if st.session_state.generating:
    status = st.session_state.job_status
    prog = max(0, status.get("progress", 0))
    st.progress(prog / 100.0, text=status.get("step", "Working..."))

    if status.get("status") == "error":
        st.error(status.get("step", "An error occurred"))
        st.session_state.generating = False
        st.rerun()
    else:
        time.sleep(1.5)
        st.rerun()

# Show completed video
if st.session_state.completed_job_id and not st.session_state.generating:
    vpath = _get_video_path(st.session_state.completed_job_id)
    if vpath:
        st.video(vpath)
        st.session_state.ready = False  # Allow new question

# Chat input
if prompt := st.chat_input("Describe the math problem you need help with..."):
    # Reset video state for new question flow
    if st.session_state.completed_job_id:
        st.session_state.completed_job_id = None
        st.session_state.ready = False

    st.session_state.messages.append({"role": "user", "content": prompt})

    # Background memory extraction
    threading.Thread(
        target=_extract_and_store_memories,
        args=(prompt, list(st.session_state.messages), st.session_state.student_id),
        daemon=True,
    ).start()

    # Get AI reply
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            memory = get_preferences(user_id=st.session_state.student_id)
            reply = _chat_reply(st.session_state.messages, student_memory=memory)

    # Check for [READY]
    if "[READY]" in reply:
        st.session_state.ready = True
        st.session_state.final_question = _extract_question(
            st.session_state.messages,
            start_idx=st.session_state.last_generate_idx,
        )
        clean_reply = reply.replace("[READY]", "").strip()
    else:
        clean_reply = reply

    st.session_state.messages.append({"role": "assistant", "content": clean_reply})
    st.rerun()
