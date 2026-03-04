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


# ── Predefined preference options ────────────────────────────────
# These map to the UI toggle buttons on the frontend.

PREFERENCE_OPTIONS = {
    "more_graphs": "Include more graphs and visual plots to illustrate concepts",
    "more_steps": "Break the solution into more detailed, smaller steps",
    "simpler": "Use simpler language and explain concepts more slowly",
    "more_color": "Use more color-coded terms to highlight different parts of equations",
    "more_examples": "Include additional examples and analogies",
    "concise": "Keep explanations brief and to the point",
    "more_diagrams": "Include more diagrams, number lines, and visual illustrations for geometry and inequality problems",
}
