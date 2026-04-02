"""
Student preference memory using mem0.

Stores and retrieves personalization preferences that shape
how the AI tutor generates video solutions — e.g. "more graphs",
"simpler explanations", "color-coded steps".

Each student has their own user_id so mem0 tracks preferences
individually. This enables personalized tutoring where different
students get different explanation styles.

Education pattern from mem0 docs:
- user_id  → persistent student profile (preferences, learning style)
- run_id   → optional session-level context (specific lesson)
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# Fallback user_id when no student is identified
DEFAULT_USER_ID = "student"

# ── Lazy-initialized mem0 client ──────────────────────────────────
_client = None


def _get_client():
    """Lazily initialise the mem0 MemoryClient.

    Returns None (with a warning) if the API key is missing,
    so the rest of the pipeline can still work without mem0.
    """
    global _client
    if _client is not None:
        return _client

    api_key = os.environ.get("MEM0_API_KEY", "")
    if not api_key:
        log.warning("MEM0_API_KEY not set — preference memory disabled")
        return None

    try:
        from mem0 import MemoryClient
        _client = MemoryClient(api_key=api_key)
        log.info("mem0 MemoryClient initialised")
        return _client
    except Exception as e:
        log.warning("Could not initialise mem0: %s", e)
        return None


def _resolve_user(user_id=None):
    """Resolve user_id: use provided value, or fall back to default."""
    return user_id or DEFAULT_USER_ID


# ── Public API ────────────────────────────────────────────────────

def add_preference(text: str, user_id: str = None) -> bool:
    """Store a student preference in mem0.

    Args:
        text: Natural-language preference, e.g.
              "I like more graphs and visual explanations"
        user_id: Student identifier (e.g. "alice", "bob_123").
                 Falls back to DEFAULT_USER_ID if not provided.

    Returns:
        True if stored successfully, False otherwise.
    """
    client = _get_client()
    if not client:
        return False

    uid = _resolve_user(user_id)
    try:
        client.add(text, user_id=uid)
        log.info("Stored preference for %s: %s", uid, text)
        return True
    except Exception as e:
        log.warning("Failed to store preference for %s: %s", uid, e)
        return False


def get_preferences(user_id: str = None) -> str:
    """Retrieve all stored student preferences as a formatted string.

    Args:
        user_id: Student identifier. Falls back to DEFAULT_USER_ID.

    Returns:
        A newline-separated summary of preferences, or "" if none found.
    """
    client = _get_client()
    if not client:
        return ""

    uid = _resolve_user(user_id)
    try:
        # mem0 v2 API requires filters param (not positional user_id)
        filters = {"AND": [{"user_id": uid}]}
        memories = client.get_all(filters=filters)

        # mem0 returns a dict with "results" key (list of memory objects)
        if not memories:
            return ""

        # Handle both list-of-dicts and dict-with-results formats
        lines = []
        if isinstance(memories, dict):
            items = memories.get("results", memories.get("memories", []))
        else:
            items = memories

        for m in items:
            if isinstance(m, dict):
                text = m.get("memory", "")
            else:
                text = str(m)
            if text:
                lines.append(f"- {text}")

        return "\n".join(lines) if lines else ""

    except Exception as e:
        log.warning("Failed to retrieve preferences for %s: %s", uid, e)
        return ""


def clear_preferences(user_id: str = None) -> bool:
    """Delete all stored preferences for a student.

    Args:
        user_id: Student identifier. Falls back to DEFAULT_USER_ID.

    Returns:
        True if cleared successfully, False otherwise.
    """
    client = _get_client()
    if not client:
        return False

    uid = _resolve_user(user_id)
    try:
        client.delete_all(user_id=uid)
        log.info("Cleared all preferences for %s", uid)
        return True
    except Exception as e:
        log.warning("Failed to clear preferences for %s: %s", uid, e)
        return False


# ── Preset video style modes ────────────────────────────────
VIDEO_PRESETS = {
    "quick_review": {
        "label": "Quick Review",
        "description": "I know the basics, just show me the method",
        "step_range": [6, 8],
        "min_visuals": 1,
        "narration_pace": "fast",
        "tone": "direct",
    },
    "standard": {
        "label": "Standard",
        "description": "Walk me through it step by step",
        "step_range": [8, 12],
        "min_visuals": 2,
        "narration_pace": "medium",
        "tone": "warm",
    },
    "deep_dive": {
        "label": "Deep Dive",
        "description": "Explain everything, I'm learning this for the first time",
        "step_range": [12, 18],
        "min_visuals": 3,
        "narration_pace": "slow",
        "tone": "encouraging",
    },
}

DEFAULT_PRESET = "standard"

# Individual override toggles (applied on top of preset)
PREFERENCE_OPTIONS = {
    "more_graphs": "Include more graphs and visual plots to illustrate concepts",
    "more_steps": "Break the solution into more detailed, smaller steps",
    "simpler": "Use simpler language and explain concepts more slowly",
    "more_color": "Use more color-coded terms to highlight different parts of equations",
    "more_examples": "Include additional examples and analogies",
    "concise": "Keep explanations brief and to the point",
    "more_diagrams": "Include more diagrams, number lines, and visual illustrations",
    "show_mistakes": "Show a common mistake before the correct approach",
    "recap": "Include a verbal recap summarizing key steps at the end",
    "analogies": "Use real-world analogies to explain abstract concepts",
}


def build_video_requirements(preset_key: str = None, active_overrides: list = None) -> str:
    """Build structured video requirements string from preset + overrides.

    Args:
        preset_key: One of "quick_review", "standard", "deep_dive".
                    Defaults to DEFAULT_PRESET.
        active_overrides: List of override keys from PREFERENCE_OPTIONS
                         (e.g. ["more_graphs", "more_color"]).

    Returns:
        A formatted string of concrete constraints for the AI prompt.
    """
    preset = VIDEO_PRESETS.get(preset_key or DEFAULT_PRESET, VIDEO_PRESETS[DEFAULT_PRESET])
    overrides = active_overrides or []

    lines = []
    lines.append(f"VIDEO STYLE: {preset['label']} — {preset['description']}")

    # Step count
    lo, hi = preset["step_range"]
    if "more_steps" in overrides:
        lo += 3
        hi += 4
    if "concise" in overrides:
        lo = max(4, lo - 2)
        hi = max(6, hi - 2)
    lines.append(f"- Step count: {lo}-{hi} steps total")

    # Visuals
    min_vis = preset["min_visuals"]
    if "more_graphs" in overrides:
        min_vis = max(min_vis, 2)
    if "more_diagrams" in overrides:
        min_vis = max(min_vis, 2)
    if min_vis > 0:
        lines.append(f"- Include at least {min_vis} visual steps (graph, tangent, area, or diagram)")

    # Color
    if "more_color" in overrides:
        lines.append("- Use color_transform animation for at least 2 key equation steps to visually distinguish terms")

    # Narration pace
    pace = preset["narration_pace"]
    if "simpler" in overrides:
        pace = "slow"
    if "concise" in overrides:
        pace = "fast"
    pace_guidance = {
        "fast": "- Narration: Keep each narration to 1 sentence. Be direct and efficient.",
        "medium": "- Narration: Use 1-2 sentences per step. Warm and clear.",
        "slow": "- Narration: Use 2-3 sentences per step. Explain the WHY behind each move. Be patient and encouraging.",
    }
    lines.append(pace_guidance.get(pace, pace_guidance["medium"]))

    # Tone
    tone = preset["tone"]
    if "simpler" in overrides:
        tone = "encouraging"
    tone_guidance = {
        "direct": "- Tone: Professional and efficient. No filler — just clear explanations.",
        "warm": "- Tone: Warm and friendly. Use natural conversational phrases.",
        "encouraging": "- Tone: Extra encouraging. Use phrases like \"You're doing great\", \"This is the tricky part but you've got it\", \"Don't worry, this is easier than it looks\".",
    }
    lines.append(tone_guidance.get(tone, tone_guidance["warm"]))

    # Specific overrides
    if "more_examples" in overrides:
        lines.append("- Include at least 1 analogy or real-world example in the narration")
    if "show_mistakes" in overrides:
        lines.append("- Before a key step, show a COMMON MISTAKE (narrate: \"Now you might be tempted to... but watch what happens\") then show the correct approach")
    if "recap" in overrides:
        lines.append("- Include a verbal recap as the second-to-last step, summarizing the key technique and result before the final highlight")
    if "analogies" in overrides:
        lines.append("- Weave real-world analogies into narrations naturally (e.g., \"think of the derivative as the speed at that exact moment\")")

    return "\n".join(lines)
