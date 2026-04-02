#!/Library/Frameworks/Python.framework/Versions/3.10/bin/python3
"""
Flask-based Math Tutor Video Generator with chatbot interface.
Run:  python3 server.py
Open: http://localhost:4000
"""
from flask import Flask, request, jsonify, send_file, send_from_directory
import json, os, uuid, threading, time, logging
from openai import OpenAI
from ai_solver import generate_solution, TUTOR_PERSONALITY
from generate import render_job
from tts import generate_narration
from merge_audio import merge_video_audio
from render_remotion import render_with_remotion
from memory import add_preference, get_preferences, clear_preferences, PREFERENCE_OPTIONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

app = Flask(__name__)
JOBS_DIR = "jobs"
os.makedirs(JOBS_DIR, exist_ok=True)

# OpenAI client for chat interactions
_oai = OpenAI()

# Cooperative cancellation: pipeline checks this set between steps
_cancelled_jobs = set()
_cancel_lock = threading.Lock()


# ── Chat System Prompt ────────────────────────────────────────────

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
video. Keep the conversation flowing naturally — you're their ongoing tutor, not
a one-shot tool.

Examples:
User: "derivatives"
→ "Sure! What function would you like to differentiate? A polynomial, trig, or something else?"

User: "find the derivative of sin(x) * e^x"
→ "Great question! I'll create a video showing how to differentiate sin(x)·eˣ using the product rule. Click Generate when you're ready! [READY]"

User (after first video): "now find the integral of that result"
→ "Nice follow-up! I'll show you how to integrate the result we just got. Hit Generate! [READY]"

IMPORTANT: Add [READY] only when you have enough information to create a
complete math tutorial video. The [READY] tag is hidden from the student."""


def _chat_reply(messages, student_memory=""):
    """Get a chat response from GPT-5.3 given conversation history."""
    system = CHAT_SYSTEM_PROMPT
    if student_memory:
        system += "\n\nStudent memories:\n" + student_memory
    gpt_msgs = [{"role": "system", "content": system}]
    for m in messages:
        gpt_msgs.append({"role": m["role"], "content": m["content"]})

    try:
        response = _oai.chat.completions.create(
            model="gpt-5.3-chat-latest",
            max_completion_tokens=256,
            messages=gpt_msgs,
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error("Chat API error: %s", e)
        return "Sorry, I'm having trouble connecting right now. Please try again in a moment."


def _extract_question(messages):
    """Build a solver-ready question from the chat conversation."""
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    if not user_msgs:
        return ""
    if len(user_msgs) == 1:
        return user_msgs[0]
    # Multi-turn: combine for full context
    return "Context: " + " → ".join(user_msgs)


# ── Memory extraction from chat ─────────────────────────────────

_MEMORY_EXTRACT_PROMPT = """\
You are a memory extraction agent for a math tutoring app. Your job is to \
capture details that help a tutor personalize future lessons — like a coach \
who takes mental notes about each student to teach them better.

Given the student's latest message (and recent chat context), extract facts \
in these categories:

HOBBIES & INTERESTS (for building relatable analogies):
- Sports, music, gaming, art, cooking, cars, etc.
- Real-world things they've mentioned enjoying or being curious about.
- Example: "Plays basketball — velocity/arc analogies will click"

LEARNING STYLE (how they like to be taught):
- Visual vs algebraic preference, fast-paced vs step-by-step
- Whether they ask for more detail or want things kept brief
- If they respond well to graphs/visuals or prefer equations
- Example: "Asks 'can you show me a picture?' — strong visual learner"

EMOTIONAL STATE & CONFIDENCE:
- Anxious, motivated, frustrated, bored, confident, struggling
- Mentions of exams, deadlines, grades, or time pressure
- Example: "Midterm in 2 days — anxious, needs confidence boosters"

MATH STRENGTHS & WEAKNESSES:
- Topics they find easy or hard (chain rule, integration by parts, etc.)
- Common mistakes they make (forgetting +C, sign errors, etc.)
- Example: "Keeps confusing product rule with chain rule"

NOT worth capturing:
- The specific math problem (handled elsewhere)
- Generic greetings or pleasantries
- Things already obvious from the math question itself

Frame each fact as TUTOR-USEFUL context — actionable coaching notes. \
Return ONLY a short bullet list (one per line, starting with "- "). \
Be selective — only 1-4 truly useful facts per message. \
If there's nothing meaningful to extract, return exactly: NONE"""


def _extract_and_store_memories(message, recent_messages, student_id):
    """Background task: extract personal facts from a chat message and store in mem0."""
    try:
        # Build context: last few messages + current
        context_msgs = [{"role": "system", "content": _MEMORY_EXTRACT_PROMPT}]
        # Include up to 4 recent messages for context
        for m in recent_messages[-4:]:
            context_msgs.append({"role": m["role"], "content": m["content"]})

        resp = _oai.chat.completions.create(
            model="gpt-4.1-nano",
            max_completion_tokens=250,
            messages=context_msgs,
        )
        extraction = resp.choices[0].message.content.strip()

        if extraction and extraction.upper() != "NONE":
            # Store each bullet as a separate memory
            for line in extraction.split("\n"):
                line = line.strip().lstrip("- ").strip()
                if line and len(line) > 3:
                    add_preference(line, user_id=student_id)
                    logging.info("mem0 stored for %s: %s", student_id or "default", line)
    except Exception as e:
        logging.warning("Memory extraction failed: %s", e)


# ── Pipeline Helpers ──────────────────────────────────────────────

def _get_student_id():
    """Extract student ID from request header (set by frontend from localStorage).
    Falls back to None which means memory.py will use DEFAULT_USER_ID.
    """
    return request.headers.get("X-Student-Id", "").strip() or None


def _update_status(job_id, status, step, progress, error=None):
    path = os.path.join(JOBS_DIR, job_id, "status.json")
    data = {"status": status, "step": step, "progress": progress}
    if error:
        data["error"] = error
    with open(path, "w") as f:
        json.dump(data, f)


def _is_cancelled(job_id):
    """Check if a job has been cancelled."""
    with _cancel_lock:
        return job_id in _cancelled_jobs


def _check_cancel(job_id):
    """Raise if the job was cancelled. Call between pipeline steps."""
    if _is_cancelled(job_id):
        raise InterruptedError("Job cancelled by user")


def _run_pipeline(job_id, question_text, renderer="manim", student_id=None, chat_history=None, preset=None, active_overrides=None):
    job_dir = os.path.join(JOBS_DIR, job_id)
    try:
        # Step 0: Fetch student preferences from mem0
        prefs = get_preferences(user_id=student_id)
        if prefs:
            logging.info("Loaded preferences for %s (job %s):\n%s",
                         student_id or "default", job_id, prefs)

        # Build chat context summary for the video generator
        # Include both student and tutor messages so the coach can read
        # the full conversational dynamic — tone, personality, interests
        chat_context = ""
        if chat_history:
            recent = chat_history[-8:]  # last 8 messages for full context
            lines = []
            for m in recent:
                role = "Student" if m.get("role") == "user" else "Tutor"
                lines.append(f"{role}: {m['content']}")
            if lines:
                chat_context = "Recent conversation with the student:\n" + "\n".join(lines)

        _check_cancel(job_id)

        # Step 1: AI generates solution (0% → 20%)
        def _progress_cb(stage):
            if stage == "coach":
                _update_status(job_id, "solving", "Tutor is planning the lesson...", 8)
            elif stage == "coach_done":
                _update_status(job_id, "solving", "Converting to animation format...", 15)
            elif stage == "producer_done":
                _update_status(job_id, "solving", "Solution ready!", 20)

        _update_status(job_id, "solving", "Tutor is planning the lesson...", 5)
        solution = generate_solution(question_text, preferences=prefs, chat_context=chat_context, preset=preset, active_overrides=active_overrides, progress_cb=_progress_cb)

        _check_cancel(job_id)

        with open(os.path.join(job_dir, "question.json"), "w") as f:
            json.dump(solution, f, indent=2)

        # Step 2: Generate narration audio (20% → 40%)
        _update_status(job_id, "narrating", "Generating voice narration...", 40)
        audio_path, step_durations = generate_narration(solution, job_dir)

        _check_cancel(job_id)

        # Write per-step audio durations into question.json so the renderer
        # can match each visual step to its narration length
        if step_durations:
            for idx, dur in step_durations.items():
                if idx < len(solution["steps"]):
                    solution["steps"][idx]["narration_duration"] = round(dur, 2)
            with open(os.path.join(job_dir, "question.json"), "w") as f:
                json.dump(solution, f, indent=2)
            logging.info("Wrote %d step durations into question.json", len(step_durations))

        # Step 3: Render video (40% → 70%)
        abs_job_dir = os.path.abspath(job_dir)
        if renderer == "remotion":
            _update_status(job_id, "rendering", "Rendering with Remotion...", 70)
            video_path = render_with_remotion(abs_job_dir)
        else:
            _update_status(job_id, "rendering", "Rendering with Manim...", 70)
            video_path = render_job(abs_job_dir)

        _check_cancel(job_id)

        # Step 4: Merge audio + video (70% → 90%)
        if audio_path and os.path.isfile(audio_path):
            _update_status(job_id, "merging", "Adding narration to video...", 90)
            final_path = os.path.join(job_dir, "final.mp4")
            merged = merge_video_audio(video_path, audio_path, final_path)
            if not merged:
                logging.warning("Audio merge failed for %s", job_id)
        else:
            logging.info("No narration for %s", job_id)

        _check_cancel(job_id)

        # Step 5: Done (100%)
        _update_status(job_id, "complete", "Video ready!", 100)

    except InterruptedError:
        logging.info("Job %s cancelled by user", job_id)
        _update_status(job_id, "cancelled", "Generation stopped.", -1, error="Cancelled by user")
    except Exception as e:
        # If user cancelled while a step was running, treat it as cancel not error
        if _is_cancelled(job_id):
            logging.info("Job %s cancelled by user (during step)", job_id)
            _update_status(job_id, "cancelled", "Generation stopped.", -1, error="Cancelled by user")
        else:
            _update_status(job_id, "error", f"Error: {str(e)}", -1, error=str(e))
    finally:
        # Clean up cancellation flag
        with _cancel_lock:
            _cancelled_jobs.discard(job_id)


# ── Chat Endpoints ────────────────────────────────────────────────

@app.route("/api/chat/new", methods=["POST"])
def api_chat_new():
    """Create a new chat session with a welcome message."""
    chat_id = str(uuid.uuid4())
    chat_dir = os.path.join(JOBS_DIR, chat_id)
    os.makedirs(chat_dir, exist_ok=True)

    welcome = (
        "Hi! I'm your math tutor. What Calculus topic would you like "
        "a video lesson on? Describe the problem or concept you need help with."
    )
    chat_data = {
        "messages": [{"role": "assistant", "content": welcome, "ts": time.time()}],
        "final_question": None,
        "ready": False,
    }
    with open(os.path.join(chat_dir, "chat.json"), "w") as f:
        json.dump(chat_data, f, indent=2)

    return jsonify({"chat_id": chat_id, "messages": chat_data["messages"], "ready": False})


@app.route("/api/chat/<chat_id>", methods=["POST"])
def api_chat_send(chat_id):
    """Send a user message and get the AI's reply."""
    chat_path = os.path.join(JOBS_DIR, chat_id, "chat.json")
    if not os.path.exists(chat_path):
        return jsonify({"error": "Chat not found"}), 404

    data = request.get_json()
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400

    with open(chat_path) as f:
        chat_data = json.load(f)

    # Add user message
    chat_data["messages"].append({"role": "user", "content": message, "ts": time.time()})

    # Background: extract personal facts and store in mem0
    student_id = _get_student_id()
    threading.Thread(
        target=_extract_and_store_memories,
        args=(message, list(chat_data["messages"]), student_id),
        daemon=True,
    ).start()

    # Load student memory for chat context
    student_memory = get_preferences(user_id=student_id)

    # Get AI reply
    reply = _chat_reply(chat_data["messages"], student_memory=student_memory)

    # Check for [READY] marker
    is_ready = "[READY]" in reply
    clean_reply = reply.replace("[READY]", "").strip()

    if is_ready:
        chat_data["ready"] = True
        # Extract question from messages AFTER the last generation marker
        # This lets the student ask multiple questions in one chat
        last_gen_idx = chat_data.get("last_generate_idx", 0)
        recent_msgs = chat_data["messages"][last_gen_idx:]
        chat_data["final_question"] = _extract_question(recent_msgs + [{"role": "user", "content": message}])

    chat_data["messages"].append({"role": "assistant", "content": clean_reply, "ts": time.time()})

    with open(chat_path, "w") as f:
        json.dump(chat_data, f, indent=2)

    return jsonify({"messages": chat_data["messages"], "ready": chat_data["ready"]})


@app.route("/api/chat/<chat_id>", methods=["GET"])
def api_chat_get(chat_id):
    """Poll current chat state."""
    chat_path = os.path.join(JOBS_DIR, chat_id, "chat.json")
    if not os.path.exists(chat_path):
        return jsonify({"error": "Chat not found"}), 404

    with open(chat_path) as f:
        chat_data = json.load(f)

    # Return all job_ids from this chat (supports multi-video)
    jobs = chat_data.get("jobs", [])
    latest_job_id = jobs[-1]["job_id"] if jobs else None

    return jsonify({
        "messages": chat_data["messages"],
        "ready": chat_data.get("ready", False),
        "job_id": latest_job_id,
        "jobs": jobs,
    })


@app.route("/api/chat/<chat_id>/generate", methods=["POST"])
def api_chat_generate(chat_id):
    """Trigger video generation from the chat context.

    Supports multiple generations per chat — each creates a new job_id
    so the student can ask follow-up questions and generate more videos.
    """
    chat_path = os.path.join(JOBS_DIR, chat_id, "chat.json")
    if not os.path.exists(chat_path):
        return jsonify({"error": "Chat not found"}), 404

    with open(chat_path) as f:
        chat_data = json.load(f)

    question = chat_data.get("final_question") or _extract_question(chat_data["messages"])
    if not question:
        return jsonify({"error": "No question found in chat"}), 400

    # Options from request body
    body = request.get_json(silent=True) or {}
    renderer = body.get("renderer", "manim")
    preset = body.get("preset", None)
    active_overrides = body.get("overrides", None)

    # Create a new job_id for each generation (allows multiple videos per chat)
    job_id = str(uuid.uuid4())
    job_dir = os.path.join(JOBS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    _update_status(job_id, "queued", "Starting...", 0)

    # Track all generated jobs in the chat data
    if "jobs" not in chat_data:
        chat_data["jobs"] = []
    chat_data["jobs"].append({"job_id": job_id, "question": question, "ts": time.time()})

    # Mark where this generation happened so next question extracts fresh
    chat_data["last_generate_idx"] = len(chat_data["messages"])
    chat_data["ready"] = False  # Reset ready for next question

    with open(chat_path, "w") as f:
        json.dump(chat_data, f, indent=2)

    student_id = _get_student_id()
    chat_history = chat_data.get("messages", [])

    thread = threading.Thread(target=_run_pipeline, args=(job_id, question, renderer, student_id, chat_history, preset, active_overrides))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id, "chat_id": chat_id, "question": question, "renderer": renderer})


@app.route("/api/chat/<chat_id>/cancel", methods=["POST"])
def api_chat_cancel(chat_id):
    """Cancel an in-progress video generation."""
    body = request.get_json(silent=True) or {}
    job_id = body.get("job_id", chat_id)  # Use job_id from body, fallback to chat_id

    with _cancel_lock:
        _cancelled_jobs.add(job_id)

    logging.info("Cancel requested for job %s", job_id)
    return jsonify({"ok": True, "job_id": job_id})


# ── Legacy + Pipeline Endpoints ───────────────────────────────────

@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json()
    question_text = data.get("question", "").strip()
    renderer = data.get("renderer", "manim")
    if not question_text:
        return jsonify({"error": "No question provided"}), 400

    job_id = str(uuid.uuid4())
    os.makedirs(os.path.join(JOBS_DIR, job_id), exist_ok=True)
    _update_status(job_id, "queued", "Starting...", 0)

    student_id = _get_student_id()
    thread = threading.Thread(target=_run_pipeline, args=(job_id, question_text, renderer, student_id))
    thread.daemon = True
    thread.start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def api_status(job_id):
    path = os.path.join(JOBS_DIR, job_id, "status.json")
    if not os.path.exists(path):
        return jsonify({"error": "Job not found"}), 404
    with open(path) as f:
        return jsonify(json.load(f))


@app.route("/api/video/<job_id>")
def api_video(job_id):
    final_path = os.path.join(JOBS_DIR, job_id, "final.mp4")
    if os.path.exists(final_path) and os.path.getsize(final_path) > 0:
        return send_file(final_path, mimetype="video/mp4")
    video_path = os.path.join(
        JOBS_DIR, job_id, "media", "videos", "scene", "720p30", "TutorialScene.mp4"
    )
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        return jsonify({"error": "Video not found"}), 404
    return send_file(video_path, mimetype="video/mp4")


@app.route("/media/<path:filename>")
def serve_media(filename):
    return send_from_directory("media", filename)


# ── Preference Endpoints ──────────────────────────────────────────

@app.route("/api/preferences", methods=["GET"])
def api_get_preferences():
    student_id = _get_student_id()
    prefs = get_preferences(user_id=student_id)
    return jsonify({"preferences": prefs, "options": PREFERENCE_OPTIONS})


@app.route("/api/preferences", methods=["POST"])
def api_set_preference():
    student_id = _get_student_id()
    data = request.get_json()
    key = data.get("key", "")
    text = data.get("text", "")
    if key and key in PREFERENCE_OPTIONS:
        text = PREFERENCE_OPTIONS[key]
    elif not text:
        return jsonify({"error": "Provide 'key' or 'text'"}), 400
    ok = add_preference(text, user_id=student_id)
    return jsonify({"ok": ok, "stored": text})


@app.route("/api/preferences", methods=["DELETE"])
def api_clear_preferences():
    student_id = _get_student_id()
    ok = clear_preferences(user_id=student_id)
    return jsonify({"ok": ok})


# ── Library Endpoint ─────────────────────────────────────────────

@app.route("/api/library")
def api_library():
    """Return a list of completed video jobs sorted by newest first."""
    videos = []
    if not os.path.isdir(JOBS_DIR):
        return jsonify({"videos": []})

    for entry in os.listdir(JOBS_DIR):
        job_dir = os.path.join(JOBS_DIR, entry)
        if not os.path.isdir(job_dir):
            continue

        # Only include completed jobs that have a video file
        status_path = os.path.join(job_dir, "status.json")
        if not os.path.isfile(status_path):
            continue
        try:
            with open(status_path) as f:
                status_data = json.load(f)
            if status_data.get("status") != "complete":
                continue
        except Exception:
            continue

        # Check that a video file actually exists
        final_path = os.path.join(job_dir, "final.mp4")
        raw_path = os.path.join(job_dir, "media", "videos", "scene", "720p30", "TutorialScene.mp4")
        has_video = (
            (os.path.isfile(final_path) and os.path.getsize(final_path) > 0) or
            (os.path.isfile(raw_path) and os.path.getsize(raw_path) > 0)
        )
        if not has_video:
            continue

        # Read question metadata
        title = "Untitled"
        question = ""
        q_path = os.path.join(job_dir, "question.json")
        if os.path.isfile(q_path):
            try:
                with open(q_path) as f:
                    q_data = json.load(f)
                title = q_data.get("title", "Untitled")
                question = q_data.get("problem_latex", "")
            except Exception:
                pass

        # Determine timestamp from chat.json or file mtime
        created_at = 0
        chat_path = os.path.join(job_dir, "chat.json")
        if os.path.isfile(chat_path):
            try:
                with open(chat_path) as f:
                    chat_data = json.load(f)
                msgs = chat_data.get("messages", [])
                if msgs:
                    created_at = msgs[0].get("ts", 0)
            except Exception:
                pass
        if created_at == 0:
            created_at = os.path.getmtime(status_path)

        has_audio = os.path.isfile(final_path) and os.path.getsize(final_path) > 0

        videos.append({
            "job_id": entry,
            "title": title,
            "question": question,
            "created_at": created_at,
            "has_audio": has_audio,
        })

    # Sort newest first
    videos.sort(key=lambda v: v["created_at"], reverse=True)
    return jsonify({"videos": videos})


# ── Frontend ──────────────────────────────────────────────────────

@app.route("/")
def index():
    return HTML_PAGE


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Math Tutor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
            background: linear-gradient(160deg, #0a0a0f 0%, #1a1a2e 100%);
            color: #e2e8f0;
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            font-weight: 300;
        }

        /* ── Name Prompt Overlay ────────── */
        .name-overlay {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(5, 5, 15, 0.85);
            backdrop-filter: blur(8px);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }
        .name-overlay.open { display: flex; }

        .name-modal {
            background: rgba(255,255,255,0.06);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 20px;
            padding: 2.5rem 2rem;
            max-width: 420px;
            width: 90%;
            text-align: center;
            box-shadow: 0 20px 60px rgba(0,0,0,0.4), 0 0 40px rgba(0,212,255,0.06);
        }
        .name-modal-icon { font-size: 2.5rem; margin-bottom: 0.5rem; }
        .name-modal h2 {
            font-size: 1.3rem;
            color: #e2e8f0;
            margin: 0 0 0.5rem;
            font-weight: 600;
        }
        .name-modal p {
            font-size: 0.9rem;
            color: rgba(255,255,255,0.5);
            margin: 0 0 1.2rem;
            line-height: 1.4;
        }
        .name-input-row {
            display: flex;
            gap: 0.5rem;
        }
        .name-input-row input {
            flex: 1;
            padding: 0.6rem 0.8rem;
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 10px;
            font-size: 0.95rem;
            outline: none;
            background: rgba(255,255,255,0.05);
            color: #e2e8f0;
        }
        .name-input-row input:focus { border-color: #00d4ff; box-shadow: 0 0 12px rgba(0,212,255,0.15); }
        .name-input-row input::placeholder { color: rgba(255,255,255,0.3); }
        .name-input-row button {
            padding: 0.6rem 1.2rem;
            background: linear-gradient(135deg, #00d4ff, #7c3aed);
            color: #ffffff;
            border: none;
            border-radius: 10px;
            font-weight: 600;
            font-size: 0.9rem;
            cursor: pointer;
            white-space: nowrap;
            transition: opacity 0.2s;
        }
        .name-input-row button:hover { opacity: 0.9; }

        .student-wrapper {
            position: relative;
        }
        .student-badge {
            font-size: 0.78rem;
            font-weight: 600;
            color: #00d4ff;
            background: rgba(0,212,255,0.1);
            padding: 0.25rem 0.6rem;
            border-radius: 12px;
            border: 1px solid rgba(0,212,255,0.25);
            cursor: pointer;
            transition: all 0.2s;
        }
        .student-badge:hover { background: rgba(0,212,255,0.18); }
        .switch-menu {
            display: none;
            position: absolute;
            top: calc(100% + 6px);
            right: 0;
            background: rgba(20,20,40,0.95);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 10px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4);
            padding: 0.5rem;
            z-index: 100;
            min-width: 160px;
        }
        .switch-menu.open { display: block; }
        .switch-menu-label {
            font-size: 0.7rem;
            color: rgba(255,255,255,0.4);
            text-transform: uppercase;
            letter-spacing: 0.04em;
            padding: 0.2rem 0.4rem 0.4rem;
        }
        .switch-menu button {
            width: 100%;
            text-align: left;
            background: none;
            border: none;
            padding: 0.4rem 0.5rem;
            font-size: 0.82rem;
            color: rgba(255,255,255,0.7);
            border-radius: 6px;
            cursor: pointer;
        }
        .switch-menu button:hover { background: rgba(255,255,255,0.08); color: #e2e8f0; }

        /* ── Header ─────────────────────── */
        .header {
            background: rgba(255,255,255,0.03);
            backdrop-filter: blur(12px);
            padding: 0.75rem 1.5rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid rgba(255,255,255,0.06);
            box-shadow: 0 1px 20px rgba(0,212,255,0.04);
            flex-shrink: 0;
            z-index: 10;
        }

        .header h1 {
            font-size: 1.1rem;
            color: #e2e8f0;
            font-weight: 600;
            white-space: nowrap;
            margin-right: 0.5rem;
        }

        .header h1 span { color: #00d4ff; text-shadow: 0 0 12px rgba(0,212,255,0.4); }

        .header-actions {
            display: flex;
            gap: 0.5rem;
            align-items: center;
            flex-wrap: wrap;
            justify-content: flex-end;
        }

        .btn-icon {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            color: rgba(255,255,255,0.6);
            border-radius: 8px;
            padding: 0.4rem 0.85rem;
            font-size: 0.8rem;
            cursor: pointer;
            transition: all 0.2s;
            font-weight: 500;
        }

        .btn-icon:hover { border-color: rgba(0,212,255,0.4); color: #00d4ff; background: rgba(0,212,255,0.08); }

        .btn-new-chat {
            background: linear-gradient(135deg, #00d4ff, #7c3aed);
            border: none;
            color: #ffffff;
            border-radius: 8px;
            padding: 0.4rem 0.85rem;
            font-size: 0.8rem;
            cursor: pointer;
            transition: all 0.2s;
            font-weight: 600;
        }

        .btn-new-chat:hover { opacity: 0.9; box-shadow: 0 0 16px rgba(0,212,255,0.2); }

        /* ── Renderer Toggle ────────────── */
        .renderer-toggle {
            display: flex;
            align-items: center;
            gap: 0.25rem;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            padding: 0.2rem;
            font-size: 0.78rem;
        }

        .renderer-toggle .rt-opt {
            padding: 0.28rem 0.65rem;
            border-radius: 6px;
            cursor: pointer;
            color: rgba(255,255,255,0.4);
            transition: all 0.2s;
            user-select: none;
            font-weight: 500;
        }

        .renderer-toggle .rt-opt:hover { color: rgba(255,255,255,0.7); }

        .renderer-toggle .rt-opt.active {
            background: rgba(0,212,255,0.15);
            color: #00d4ff;
            box-shadow: 0 0 8px rgba(0,212,255,0.1);
        }

        /* ── Wizard: Preset Cards ────────── */
        .wizard-section {
            margin-top: 0.6rem;
            animation: fadeIn 0.35s ease;
        }

        .wizard-label {
            font-size: 0.88rem;
            color: rgba(255,255,255,0.6);
            margin-bottom: 0.6rem;
            font-weight: 400;
        }

        .preset-cards {
            display: flex;
            gap: 0.6rem;
            flex-wrap: wrap;
        }

        .preset-card {
            flex: 1;
            min-width: 130px;
            max-width: 200px;
            padding: 0.9rem 0.8rem;
            background: rgba(255,255,255,0.04);
            backdrop-filter: blur(8px);
            border: 1.5px solid rgba(255,255,255,0.08);
            border-radius: 14px;
            cursor: pointer;
            transition: all 0.25s ease;
            text-align: center;
        }

        .preset-card:hover {
            border-color: rgba(0,212,255,0.3);
            background: rgba(0,212,255,0.06);
        }

        .preset-card.active {
            border-color: #00d4ff;
            background: rgba(0,212,255,0.1);
            box-shadow: 0 0 20px rgba(0,212,255,0.15);
        }

        .preset-card-icon {
            font-size: 1.6rem;
            margin-bottom: 0.35rem;
            display: block;
        }

        .preset-card-name {
            font-size: 0.85rem;
            color: #e2e8f0;
            font-weight: 600;
            margin-bottom: 0.2rem;
        }

        .preset-card-desc {
            font-size: 0.72rem;
            color: rgba(255,255,255,0.4);
            line-height: 1.3;
        }

        /* ── Wizard: Override Chips ────────── */
        .override-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
            margin-top: 0.1rem;
        }

        .override-chip {
            padding: 0.32rem 0.75rem;
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
            background: rgba(255,255,255,0.04);
            font-size: 0.78rem;
            color: rgba(255,255,255,0.55);
            cursor: pointer;
            transition: all 0.2s;
            font-weight: 400;
            user-select: none;
        }

        .override-chip:hover {
            border-color: rgba(0,212,255,0.3);
            color: rgba(255,255,255,0.8);
        }

        .override-chip.active {
            background: rgba(0,212,255,0.15);
            border-color: #00d4ff;
            color: #00d4ff;
            box-shadow: 0 0 10px rgba(0,212,255,0.12);
            font-weight: 500;
        }

        /* ── Generate Button (wizard) ──── */
        .btn-generate-wizard {
            background: linear-gradient(135deg, #00d4ff, #7c3aed);
            color: #ffffff;
            border: none;
            border-radius: 14px;
            padding: 0.85rem 2.4rem;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            display: inline-block;
            letter-spacing: 0.02em;
            animation: subtlePulse 3s ease-in-out infinite;
            box-shadow: 0 0 24px rgba(0,212,255,0.2);
        }

        .btn-generate-wizard:hover {
            opacity: 0.92;
            box-shadow: 0 0 32px rgba(0,212,255,0.3);
            transform: translateY(-1px);
        }

        .btn-generate-wizard:disabled {
            background: rgba(255,255,255,0.1);
            color: rgba(255,255,255,0.3);
            cursor: not-allowed;
            animation: none;
            box-shadow: none;
        }

        @keyframes subtlePulse {
            0%, 100% { box-shadow: 0 0 24px rgba(0,212,255,0.2); }
            50% { box-shadow: 0 0 32px rgba(0,212,255,0.35), 0 0 8px rgba(124,58,237,0.2); }
        }

        /* ── Chat Area ──────────────────── */
        .chat-area {
            flex: 1;
            overflow-y: auto;
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
            background: transparent;
        }

        .chat-area::-webkit-scrollbar { width: 5px; }
        .chat-area::-webkit-scrollbar-track { background: transparent; }
        .chat-area::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 3px; }

        /* ── Message Bubbles ────────────── */
        .msg {
            max-width: 78%;
            padding: 0.8rem 1.1rem;
            border-radius: 16px;
            font-size: 0.9rem;
            line-height: 1.6;
            animation: fadeIn 0.25s ease;
            word-wrap: break-word;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(6px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .msg-ai {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255,255,255,0.1);
            border-left: 3px solid rgba(0,212,255,0.4);
            align-self: flex-start;
            border-bottom-left-radius: 4px;
            color: #e2e8f0;
        }

        .msg-user {
            background: linear-gradient(135deg, #00d4ff, #7c3aed);
            border: none;
            align-self: flex-end;
            border-bottom-right-radius: 4px;
            color: #ffffff;
        }

        .msg-system {
            align-self: center;
            background: transparent;
            color: rgba(255,255,255,0.45);
            font-size: 0.82rem;
            padding: 0.3rem;
        }

        /* ── Sample Chips ───────────────── */
        .chips {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-top: 0.5rem;
            max-width: 700px;
        }

        .chip {
            background: rgba(255,255,255,0.04);
            backdrop-filter: blur(8px);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 0.55rem 0.95rem;
            font-size: 0.82rem;
            color: rgba(255,255,255,0.65);
            cursor: pointer;
            transition: all 0.25s;
            font-weight: 400;
        }

        .chip:hover {
            border-color: rgba(0,212,255,0.4);
            color: #00d4ff;
            background: rgba(0,212,255,0.08);
            box-shadow: 0 0 16px rgba(0,212,255,0.1);
            transform: translateY(-2px);
        }

        /* ── Progress (inline) ──────────── */
        .progress-inline { width: 100%; max-width: 380px; margin-top: 0.4rem; }

        .progress-track {
            background: rgba(255,255,255,0.08);
            border-radius: 8px;
            height: 8px;
            overflow: hidden;
            margin-bottom: 0.4rem;
        }

        .progress-fill {
            height: 100%;
            width: 0%;
            background: linear-gradient(90deg, #00d4ff, #7c3aed);
            border-radius: 8px;
            transition: width 0.5s ease;
        }

        .progress-label {
            font-size: 0.82rem;
            color: #00d4ff;
            font-weight: 500;
        }

        .btn-stop-gen {
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            margin-top: 0.5rem;
            padding: 0.35rem 0.9rem;
            font-size: 0.78rem;
            font-weight: 600;
            color: #f87171;
            background: rgba(239,68,68,0.1);
            border: 1px solid rgba(239,68,68,0.25);
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .btn-stop-gen:hover {
            background: rgba(239,68,68,0.18);
            border-color: rgba(239,68,68,0.4);
        }
        .btn-stop-gen:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* ── Video (inline) ─────────────── */
        .video-inline {
            width: 100%;
            max-width: 600px;
            border-radius: 12px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.3), 0 0 20px rgba(0,212,255,0.06);
            margin-top: 0.4rem;
        }

        /* ── Typing Indicator ───────────── */
        .typing { display: flex; gap: 4px; padding: 0.3rem 0; }

        .typing span {
            width: 6px; height: 6px;
            background: #00d4ff;
            border-radius: 50%;
            animation: bounce 1.4s infinite;
        }

        .typing span:nth-child(2) { animation-delay: 0.2s; }
        .typing span:nth-child(3) { animation-delay: 0.4s; }

        @keyframes bounce {
            0%, 60%, 100% { transform: translateY(0); }
            30% { transform: translateY(-6px); }
        }

        /* ── Input Bar ──────────────────── */
        .input-bar {
            padding: 0.75rem 1.5rem;
            background: rgba(255,255,255,0.03);
            backdrop-filter: blur(12px);
            border-top: 1px solid rgba(255,255,255,0.06);
            display: flex;
            gap: 0.5rem;
            align-items: center;
            flex-shrink: 0;
        }

        .input-bar input {
            flex: 1;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 24px;
            padding: 0.7rem 1.2rem;
            font-size: 0.9rem;
            color: #e2e8f0;
            outline: none;
            transition: border-color 0.2s, box-shadow 0.2s;
        }

        .input-bar input:focus { border-color: #00d4ff; box-shadow: 0 0 16px rgba(0,212,255,0.12); }
        .input-bar input::placeholder { color: rgba(255,255,255,0.3); }

        .btn-send {
            background: linear-gradient(135deg, #00d4ff, #7c3aed);
            color: #ffffff;
            border: none;
            border-radius: 24px;
            padding: 0.7rem 1.4rem;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            white-space: nowrap;
        }

        .btn-send:hover { opacity: 0.9; box-shadow: 0 0 16px rgba(0,212,255,0.2); }
        .btn-send:disabled { background: rgba(255,255,255,0.1); color: rgba(255,255,255,0.3); cursor: not-allowed; }

        /* ── Library Panel ─────────────── */
        .library-panel {
            position: fixed;
            top: 0;
            right: 0;
            width: 340px;
            height: 100vh;
            background: rgba(15,15,30,0.95);
            backdrop-filter: blur(20px);
            border-left: 1px solid rgba(255,255,255,0.08);
            transform: translateX(100%);
            transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            z-index: 100;
            display: flex;
            flex-direction: column;
            box-shadow: -4px 0 32px rgba(0,0,0,0.4);
        }

        .library-panel.open { transform: translateX(0); }

        .library-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.85rem 1rem;
            border-bottom: 1px solid rgba(255,255,255,0.08);
            flex-shrink: 0;
        }

        .library-header h2 {
            font-size: 0.95rem;
            color: #e2e8f0;
            font-weight: 600;
        }

        .library-close {
            background: none;
            border: none;
            color: rgba(255,255,255,0.4);
            font-size: 1.2rem;
            cursor: pointer;
            padding: 0.2rem 0.5rem;
            border-radius: 6px;
            transition: all 0.2s;
        }

        .library-close:hover { color: #e2e8f0; background: rgba(255,255,255,0.08); }

        .library-list {
            flex: 1;
            overflow-y: auto;
            padding: 0.6rem;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        .library-list::-webkit-scrollbar { width: 5px; }
        .library-list::-webkit-scrollbar-track { background: transparent; }
        .library-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 3px; }

        .library-card {
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 10px;
            padding: 0.75rem 0.9rem;
            cursor: pointer;
            transition: all 0.2s;
        }

        .library-card:hover {
            border-color: rgba(0,212,255,0.3);
            background: rgba(0,212,255,0.06);
            box-shadow: 0 0 16px rgba(0,212,255,0.08);
        }

        .library-card-title {
            font-size: 0.87rem;
            color: #e2e8f0;
            font-weight: 500;
            line-height: 1.35;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }

        .library-card-question {
            font-size: 0.78rem;
            color: rgba(255,255,255,0.35);
            margin-top: 0.25rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .library-card-meta {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-top: 0.35rem;
            font-size: 0.72rem;
            color: rgba(255,255,255,0.35);
        }

        .library-card-meta .audio-badge {
            background: rgba(0,212,255,0.1);
            color: #00d4ff;
            padding: 0.12rem 0.5rem;
            border-radius: 10px;
            font-size: 0.68rem;
            font-weight: 500;
        }

        .library-empty {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            flex: 1;
            color: rgba(255,255,255,0.35);
            font-size: 0.87rem;
            text-align: center;
            padding: 2rem;
            gap: 0.5rem;
        }

        .library-empty span { font-size: 2rem; }

        /* Overlay behind panel */
        .library-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.4);
            z-index: 99;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s;
        }

        .library-overlay.open {
            opacity: 1;
            pointer-events: auto;
        }
    </style>
</head>
<body>
    <!-- Name Prompt Overlay (first visit) -->
    <div class="name-overlay" id="name-overlay">
        <div class="name-modal">
            <div class="name-modal-icon">&#127891;</div>
            <h2>Welcome to Math Tutor!</h2>
            <p>What's your name? This helps personalize your learning experience.</p>
            <div class="name-input-row">
                <input type="text" id="name-input" placeholder="Your first name..."
                       maxlength="30"
                       onkeydown="if(event.key==='Enter'){event.preventDefault();submitName();}">
                <button onclick="submitName()">Get Started</button>
            </div>
        </div>
    </div>

    <!-- Header -->
    <div class="header">
        <h1><span>&#10022;</span> Math Tutor</h1>
        <div class="header-actions">
            <div class="student-wrapper" id="student-wrapper" style="display:none;">
                <span class="student-badge" id="student-name" onclick="showSwitchMenu(event)"></span>
                <div class="switch-menu" id="switch-menu">
                    <div class="switch-menu-label">Switch student</div>
                    <button onclick="switchStudent()">Log out &amp; change name</button>
                </div>
            </div>
            <div class="renderer-toggle" title="Choose video renderer">
                <span class="rt-opt active" data-r="manim" onclick="setRenderer(this)">Manim</span>
                <span class="rt-opt" data-r="remotion" onclick="setRenderer(this)">Remotion</span>
            </div>
            <button class="btn-icon" onclick="toggleLibrary()">&#128218; Library</button>
            <button class="btn-new-chat" onclick="newChat()">+ New Chat</button>
        </div>
    </div>

    <!-- Chat Area -->
    <div class="chat-area" id="chat-area"></div>

    <!-- Library Overlay -->
    <div class="library-overlay" id="library-overlay" onclick="toggleLibrary()"></div>

    <!-- Library Panel -->
    <div class="library-panel" id="library-panel">
        <div class="library-header">
            <h2>&#127909; Video Library</h2>
            <button class="library-close" onclick="toggleLibrary()">&times;</button>
        </div>
        <div class="library-list" id="library-list">
            <div class="library-empty">
                <span>&#127916;</span>
                No videos yet — start a chat!
            </div>
        </div>
    </div>

    <!-- Input Bar -->
    <div class="input-bar">
        <input type="text" id="chat-input"
               placeholder="Describe the math problem you need help with..."
               onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMessage();}">
        <button class="btn-send" id="btn-send" onclick="sendMessage()">Send</button>
    </div>

    <script>
    /* ═══════════════════════════════════════════════
       State
    ═══════════════════════════════════════════════ */
    let chatId   = null;
    let ready    = false;
    let generating = false;
    let pollTimer  = null;
    let currentJobId = null;
    let renderer   = 'manim';
    let studentId  = localStorage.getItem('studentId') || '';

    const chatArea  = document.getElementById('chat-area');
    const chatInput = document.getElementById('chat-input');
    const btnSend   = document.getElementById('btn-send');

    /* Helper: include student ID header on all API calls */
    function apiHeaders(extra) {
        const h = { 'X-Student-Id': studentId, ...(extra || {}) };
        return h;
    }

    /* ═══════════════════════════════════════════════
       Initialization
    ═══════════════════════════════════════════════ */
    async function init() {
        if (!studentId) {
            showNamePrompt();
            return; /* init continues after name is set */
        }
        updateProfileDisplay();
        await loadPrefs();
        await newChat();
    }

    function showNamePrompt() {
        const overlay = document.getElementById('name-overlay');
        overlay.classList.add('open');
        const inp = document.getElementById('name-input');
        inp.focus();
    }

    function submitName() {
        const inp  = document.getElementById('name-input');
        const name = inp.value.trim();
        if (!name) return;

        /* Create a URL-safe student ID from the name */
        studentId = name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
        localStorage.setItem('studentId', studentId);
        localStorage.setItem('studentName', name);

        document.getElementById('name-overlay').classList.remove('open');
        updateProfileDisplay();
        loadPrefs();
        newChat();
    }

    function updateProfileDisplay() {
        const nameEl = document.getElementById('student-name');
        const wrapper = document.getElementById('student-wrapper');
        const displayName = localStorage.getItem('studentName') || studentId;
        if (nameEl && displayName) {
            nameEl.textContent = displayName;
            if (wrapper) wrapper.style.display = 'inline-block';
        }
    }

    function showSwitchMenu(e) {
        e.stopPropagation();
        const menu = document.getElementById('switch-menu');
        menu.classList.toggle('open');
        /* Close on outside click */
        const close = () => { menu.classList.remove('open'); document.removeEventListener('click', close); };
        setTimeout(() => document.addEventListener('click', close), 0);
    }

    function switchStudent() {
        localStorage.removeItem('studentId');
        localStorage.removeItem('studentName');
        location.reload();
    }

    async function newChat() {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        ready = false;
        generating = false;
        chatArea.innerHTML = '';

        try {
            const res  = await fetch('/api/chat/new', { method: 'POST', headers: apiHeaders() });
            const data = await res.json();
            chatId = data.chat_id;

            for (const msg of data.messages) {
                addBubble(msg.role, msg.content);
            }
            addChips();
            scrollBottom();
            chatInput.value = '';
            chatInput.focus();
        } catch (e) {
            addBubble('system', 'Failed to start chat. Is the server running?');
        }
    }

    /* ═══════════════════════════════════════════════
       Send Message
    ═══════════════════════════════════════════════ */
    async function sendMessage() {
        const text = chatInput.value.trim();
        if (!text || generating) return;

        chatInput.value = '';
        addBubble('user', text);
        removeChips();
        showTyping();
        btnSend.disabled = true;
        scrollBottom();

        try {
            const res = await fetch('/api/chat/' + chatId, {
                method: 'POST',
                headers: apiHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ message: text }),
            });
            const data = await res.json();

            hideTyping();

            // Show the latest AI reply
            const aiMsgs = data.messages.filter(m => m.role === 'assistant');
            const lastAi = aiMsgs[aiMsgs.length - 1];
            if (lastAi) addBubble('assistant', lastAi.content);

            // If GPT marked [READY], show Generate button
            if (data.ready && !ready) {
                ready = true;
                addGenerateButton();
            }
        } catch (e) {
            hideTyping();
            addBubble('system', 'Network error — please try again.');
        }

        btnSend.disabled = false;
        scrollBottom();
        chatInput.focus();
    }

    function useSample(text) {
        chatInput.value = text;
        sendMessage();
    }

    /* ═══════════════════════════════════════════════
       Generate Video
    ═══════════════════════════════════════════════ */
    async function generateVideo() {
        if (generating) return;
        generating = true;
        ready = false;  // Reset so next [READY] from a new question triggers the button again

        const genBtn = document.querySelector('.btn-generate-wizard');
        if (genBtn) genBtn.disabled = true;

        addProgress();
        scrollBottom();

        try {
            var activeOverrides = [];
            document.querySelectorAll('.override-chip.active').forEach(function(b) {
                if (b.dataset.key) activeOverrides.push(b.dataset.key);
            });

            const res  = await fetch('/api/chat/' + chatId + '/generate', {
                method: 'POST',
                headers: apiHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ renderer: renderer, preset: currentPreset, overrides: activeOverrides }),
            });
            const data = await res.json();
            currentJobId = data.job_id;  // Store for cancel

            let pollCount = 0;
            const maxPolls = 300; // 10 minutes at 2s intervals
            pollTimer = setInterval(async () => {
                pollCount++;
                if (pollCount >= maxPolls) {
                    clearInterval(pollTimer);
                    pollTimer = null;
                    removeProgress();
                    addBubble('system', 'Generation timed out after 10 minutes. Please try again.');
                    addGenerateButton();
                    generating = false;
                    scrollBottom();
                    return;
                }
                try {
                    const sRes    = await fetch('/api/status/' + data.job_id);
                    const status  = await sRes.json();
                    const pct     = Math.max(0, status.progress);

                    updateProgress(pct, status.step);

                    if (status.status === 'complete') {
                        clearInterval(pollTimer);
                        pollTimer = null;
                        removeProgress();
                        addVideo(data.job_id);
                        generating = false;
                        scrollBottom();
                    } else if (status.status === 'cancelled') {
                        clearInterval(pollTimer);
                        pollTimer = null;
                        removeProgress();
                        // Remove old disabled generate button before adding fresh one
                        document.querySelectorAll('.generate-wrap').forEach(function(w) { w.remove(); });
                        addBubble('system', 'Generation stopped. You can try again when ready.');
                        addGenerateButton();
                        generating = false;
                        scrollBottom();
                    } else if (status.status === 'error') {
                        clearInterval(pollTimer);
                        pollTimer = null;
                        removeProgress();
                        addBubble('system', '\u26a0 ' + (status.error || 'Generation failed'));
                        addGenerateButton();
                        generating = false;
                        scrollBottom();
                    }
                } catch (_) { /* keep polling */ }
            }, 2000);
        } catch (e) {
            removeProgress();
            addBubble('system', '\u26a0 Failed to start generation.');
            generating = false;
        }
    }

    /* ═══════════════════════════════════════════════
       Cancel Generation
    ═══════════════════════════════════════════════ */
    async function cancelGeneration() {
        if (!chatId || !generating) return;

        const stopBtn = document.getElementById('btn-stop');
        if (stopBtn) {
            stopBtn.disabled = true;
            stopBtn.textContent = 'Stopping...';
        }

        try {
            await fetch('/api/chat/' + chatId + '/cancel', {
                method: 'POST',
                headers: apiHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ job_id: currentJobId }),
            });
        } catch (e) {
            /* polling will handle the state change */
        }
    }
    // Expose globally for onclick
    window.cancelGeneration = cancelGeneration;

    /* ═══════════════════════════════════════════════
       DOM Helpers
    ═══════════════════════════════════════════════ */
    function addBubble(role, text) {
        const div = document.createElement('div');
        if (role === 'assistant')    div.className = 'msg msg-ai';
        else if (role === 'user')    div.className = 'msg msg-user';
        else                         div.className = 'msg msg-system';
        div.textContent = text;
        chatArea.appendChild(div);
        scrollBottom();
    }

    function addChips() {
        const wrap = document.createElement('div');
        wrap.className = 'chips';
        wrap.id = 'sample-chips';
        const samples = [
            'Find the derivative of x\u2074 - 3x\u00b2 + 5',
            'Evaluate lim(x\u21920) of sin(x)/x',
            'Find \u222b(4x\u00b3 + 2x) dx',
            'What is the derivative of ln(x\u00b2+1)?',
            'Find the area under y = x\u00b2 from 0 to 3',
            'Solve: d/dx [sin(x)\u00b7cos(x)]',
            'Evaluate lim(x\u2192\u221e) of (3x\u00b2+1)/(x\u00b2-4)',
            'Find the tangent line to y=e\u02e3 at x=1',
        ];
        for (const s of samples) {
            const chip = document.createElement('span');
            chip.className = 'chip';
            chip.textContent = s;
            chip.onclick = () => useSample(s);
            wrap.appendChild(chip);
        }
        chatArea.appendChild(wrap);
    }

    function removeChips() {
        const c = document.getElementById('sample-chips');
        if (c) c.remove();
    }

    function addGenerateButton() {
        /* ── Wizard: conversational preference flow ── */
        var wrap = document.createElement('div');
        wrap.className = 'generate-wrap msg msg-ai';
        wrap.style.cssText = 'max-width:90%;border-left:3px solid rgba(0,212,255,0.4);';

        /* Step 1: Preset cards */
        var s1 = document.createElement('div');
        s1.className = 'wizard-section';
        s1.innerHTML =
            '<div class="wizard-label">What kind of video would you like?</div>' +
            '<div class="preset-cards">' +
            '  <div class="preset-card" data-preset="quick_review">' +
            '    <span class="preset-card-icon">&#9889;</span>' +
            '    <div class="preset-card-name">Quick Review</div>' +
            '    <div class="preset-card-desc">Just the method, keep it brief</div>' +
            '  </div>' +
            '  <div class="preset-card active" data-preset="standard">' +
            '    <span class="preset-card-icon">&#128214;</span>' +
            '    <div class="preset-card-name">Standard</div>' +
            '    <div class="preset-card-desc">Walk me through step by step</div>' +
            '  </div>' +
            '  <div class="preset-card" data-preset="deep_dive">' +
            '    <span class="preset-card-icon">&#128300;</span>' +
            '    <div class="preset-card-name">Deep Dive</div>' +
            '    <div class="preset-card-desc">Explain everything in detail</div>' +
            '  </div>' +
            '</div>';
        wrap.appendChild(s1);

        /* Step 2: Override chips */
        var s2 = document.createElement('div');
        s2.className = 'wizard-section';
        s2.style.marginTop = '1rem';
        s2.innerHTML =
            '<div class="wizard-label">Any special requests?</div>' +
            '<div class="override-chips">' +
            '  <span class="override-chip" data-key="more_graphs">&#128202; More Visuals</span>' +
            '  <span class="override-chip" data-key="more_color">&#127912; Color-Coded</span>' +
            '  <span class="override-chip" data-key="simpler">&#128161; Simpler Language</span>' +
            '  <span class="override-chip" data-key="show_mistakes">&#127919; Show Common Mistakes</span>' +
            '  <span class="override-chip" data-key="recap">&#128203; Recap at End</span>' +
            '  <span class="override-chip" data-key="analogies">&#127758; Real-World Analogies</span>' +
            '</div>';
        wrap.appendChild(s2);

        /* Step 3: Generate button */
        var s3 = document.createElement('div');
        s3.className = 'wizard-section';
        s3.style.cssText = 'margin-top:1.2rem;text-align:center;';
        var btn = document.createElement('button');
        btn.className = 'btn-generate-wizard';
        btn.innerHTML = '&#10024; Generate My Video';
        btn.onclick = generateVideo;
        s3.appendChild(btn);
        wrap.appendChild(s3);

        chatArea.appendChild(wrap);

        /* Wire up preset card selection */
        wrap.querySelectorAll('.preset-card').forEach(function(card) {
            card.addEventListener('click', function() {
                wrap.querySelectorAll('.preset-card').forEach(function(c) { c.classList.remove('active'); });
                card.classList.add('active');
                currentPreset = card.dataset.preset;
            });
        });

        /* Wire up override chip toggles */
        wrap.querySelectorAll('.override-chip').forEach(function(chip) {
            if (activePrefs.has(chip.dataset.key)) chip.classList.add('active');
            chip.addEventListener('click', function() {
                var key = chip.dataset.key;
                if (activePrefs.has(key)) {
                    activePrefs.delete(key);
                    chip.classList.remove('active');
                } else {
                    activePrefs.add(key);
                    chip.classList.add('active');
                }
            });
        });

        scrollBottom();
    }

    function showTyping() {
        const div = document.createElement('div');
        div.className = 'msg msg-ai';
        div.id = 'typing-indicator';
        div.innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';
        chatArea.appendChild(div);
        scrollBottom();
    }

    function hideTyping() {
        const t = document.getElementById('typing-indicator');
        if (t) t.remove();
    }

    function addProgress() {
        const div = document.createElement('div');
        div.className = 'msg msg-ai';
        div.id = 'progress-msg';
        div.innerHTML =
            '<div class="progress-inline">' +
            '  <div class="progress-label" id="prog-label">Starting...</div>' +
            '  <div class="progress-track">' +
            '    <div class="progress-fill" id="prog-bar"></div>' +
            '  </div>' +
            '  <button class="btn-stop-gen" id="btn-stop" onclick="cancelGeneration()">' +
            '    \u25a0  Stop Generating' +
            '  </button>' +
            '</div>';
        chatArea.appendChild(div);
        scrollBottom();
    }

    function updateProgress(pct, label) {
        const bar = document.getElementById('prog-bar');
        const lbl = document.getElementById('prog-label');
        if (bar) bar.style.width = pct + '%';
        if (lbl) lbl.textContent = label + ' (' + pct + '%)';
    }

    function removeProgress() {
        const p = document.getElementById('progress-msg');
        if (p) p.remove();
    }

    function addVideo(jobId) {
        const div = document.createElement('div');
        div.className = 'msg msg-ai';
        div.style.maxWidth = '88%';
        div.innerHTML =
            '<div style="margin-bottom:0.4rem;font-size:0.85rem;color:#00d4ff;font-weight:600;">' +
            '\u2713 Your video is ready!</div>' +
            '<video class="video-inline" controls autoplay>' +
            '  <source src="/api/video/' + jobId + '" type="video/mp4">' +
            '</video>' +
            '<div style="margin-top:0.6rem;">' +
            '  <button class="btn-new-chat" onclick="newChat()">Ask another question</button>' +
            '</div>';
        chatArea.appendChild(div);
        scrollBottom();
    }

    function scrollBottom() {
        requestAnimationFrame(() => {
            chatArea.scrollTop = chatArea.scrollHeight;
        });
    }

    /* ═══════════════════════════════════════════════
       Renderer Toggle
    ═══════════════════════════════════════════════ */
    function setRenderer(el) {
        renderer = el.dataset.r;
        document.querySelectorAll('.rt-opt').forEach(o => o.classList.remove('active'));
        el.classList.add('active');
    }

    /* ═══════════════════════════════════════════════
       Preferences + Presets
    ═══════════════════════════════════════════════ */
    const activePrefs = new Set();
    let currentPreset = 'standard';

    async function clearPrefs() {
        try {
            await fetch('/api/preferences', { method: 'DELETE', headers: apiHeaders() });
            activePrefs.clear();
            currentPreset = 'standard';
            document.querySelectorAll('.override-chip').forEach(function(c) { c.classList.remove('active'); });
            document.querySelectorAll('.preset-card').forEach(function(c) { c.classList.remove('active'); });
            var stdCard = document.querySelector('.preset-card[data-preset="standard"]');
            if (stdCard) stdCard.classList.add('active');
        } catch (e) { /* ignore */ }
    }

    async function loadPrefs() {
        // Load mem0 preferences as student profile context (free-text only).
        // Toggle states are local-only and not restored from mem0.
        try {
            const res  = await fetch('/api/preferences', { headers: apiHeaders() });
            const data = await res.json();
            // data.preferences is available for the AI prompt via the generate endpoint;
            // we no longer try to reconstruct toggle button state from it.
        } catch (e) { /* mem0 unavailable — still works */ }
    }

    /* ═══════════════════════════════════════════════
       Library
    ═══════════════════════════════════════════════ */
    let libraryOpen = false;

    function toggleLibrary() {
        libraryOpen = !libraryOpen;
        document.getElementById('library-panel').classList.toggle('open', libraryOpen);
        document.getElementById('library-overlay').classList.toggle('open', libraryOpen);
        if (libraryOpen) loadLibrary();
    }

    async function loadLibrary() {
        const list = document.getElementById('library-list');
        list.innerHTML = '<div class="library-empty" style="color:#00d4ff;font-size:0.8rem;">Loading...</div>';

        try {
            const res  = await fetch('/api/library', { headers: apiHeaders() });
            const data = await res.json();
            const videos = data.videos || [];

            if (videos.length === 0) {
                list.innerHTML = '<div class="library-empty"><span>&#127916;</span>No videos yet \u2014 start a chat!</div>';
                return;
            }

            list.innerHTML = '';
            for (const v of videos) {
                const card = document.createElement('div');
                card.className = 'library-card';
                card.onclick = () => playFromLibrary(v.job_id, v.title);

                const questionDisplay = v.question
                    ? v.question.replace(/\\\\/g, '\\')
                    : '';

                card.innerHTML =
                    '<div class="library-card-title">' + escHtml(v.title) + '</div>' +
                    (questionDisplay ? '<div class="library-card-question">' + escHtml(questionDisplay) + '</div>' : '') +
                    '<div class="library-card-meta">' +
                    '  <span>' + timeAgo(v.created_at) + '</span>' +
                    (v.has_audio ? '<span class="audio-badge">\u266a audio</span>' : '') +
                    '</div>';

                list.appendChild(card);
            }
        } catch (e) {
            list.innerHTML = '<div class="library-empty">Could not load library.</div>';
        }
    }

    function playFromLibrary(jobId, title) {
        // Close the library panel
        toggleLibrary();

        // Clear chat area and show the video
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        generating = false;
        chatArea.innerHTML = '';

        // Title message
        addBubble('assistant', '\u25b6 ' + title);

        // Video player
        addVideo(jobId);
    }

    function timeAgo(ts) {
        const now = Date.now() / 1000;
        const diff = Math.max(0, now - ts);

        if (diff < 60)    return 'just now';
        if (diff < 3600)  return Math.floor(diff / 60) + 'm ago';
        if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
        if (diff < 172800) return 'yesterday';
        if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';

        const d = new Date(ts * 1000);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    }

    function escHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    /* ── Boot ── */
    init();
    </script>
</body>
</html>"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 4000))
    app.run(host="0.0.0.0", port=port, debug=(os.environ.get("RAILWAY_ENVIRONMENT") is None))
