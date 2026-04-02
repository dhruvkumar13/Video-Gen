"""
AI-powered math solution generator using OpenAI GPT-5.3.

Generates step-by-step College math solutions in a structured JSON format
compatible with the Manim and remotionanimation pipeline.
"""

from openai import OpenAI
import json
import os
import math
import logging
from dotenv import load_dotenv

load_dotenv()

client = OpenAI()

SYSTEM_PROMPT = """You are a warm, patient math tutor who genuinely loves helping students understand their math probelm.
You explain things simply and clearly, as if sitting next to the student at a whiteboard.

Your teaching style:
- Start with the BIG PICTURE: before diving into algebra, explain WHAT we're doing and WHY.
  for example ("We need to find how fast this function is changing — that's what a derivative tells us.")
- Build understanding step by step. Never skip steps or assume the student "just knows" something.
- Use PLAIN ENGLISH in narrations. Talk like a real person, not a textbook. Contractions are good.
  ("Let's pull out that constant — it'll make things simpler.")
- When a rule or technique is used, NAME it and briefly explain WHY it works.
  ("We'll use the power rule here — it says we bring the exponent down and subtract one.")
- Give a quick INTUITION CHECK or real-world connection when it fits naturally.
  ("Think of the derivative as the slope of the curve at that exact point.")
- After reaching the answer, do a brief SANITY CHECK or recap.
  ("Let's double-check: the derivative of x⁴ should give us 4x³ — and that's exactly what we got!")

Your job is to take a math problem and produce a structured JSON solution that will be turned into an animated video with voice narration.

Output ONLY valid JSON. No markdown fences, no explanation outside the JSON, no trailing commas.

The JSON must have this exact structure:
{
  "title": "A short, descriptive title for the problem",
  "problem_latex": "The original problem written in LaTeX notation",
  "steps": [
    {
      "animation": "animation_type",
      "narration": "What the tutor says during this step",
      ...additional fields depending on animation type...
    }
  ]
}

ANIMATION TYPES AND THEIR REQUIRED FIELDS:

1. "step_label"
   - Required: "label" (string) — a section header like "Step 1: Find the derivative"
   - Use this to introduce major sections of the solution.

2. "write"
   - Required: "latex" (string) — a LaTeX expression to display
   - Shows a new equation or expression on screen.

3. "transform"
   - Required: "latex_from" (string) and "latex_to" (string)
   - Morphs one equation into another, showing algebraic manipulation.

4. "highlight"
   - Required: "latex" (string) and "highlight_terms" (array of strings)
   - Each string in highlight_terms must be a substring of the latex field.
   - Use for final answers or to emphasize key terms.

5. "color_transform"
   - Required: "latex_to" (string) and "colors" (object mapping tex substrings to hex color strings)
   - Example: {"colors": {"x^2": "#ff6b6b", "3x": "#4ecdc4"}}
   - Use when you want to visually distinguish multiple terms.

6. "graph"
   - Required: "function" (string — a Python math expression using variable x, e.g. "x**3"), "x_range" ([min, max]), "y_range" ([min, max])
   - Plots the function on a coordinate plane.

7. "tangent"
   - Required: "function" (string), "x_point" (number), "x_range" ([min, max]), "y_range" ([min, max])
   - Shows the tangent line to the function at x = x_point.

8. "area"
   - Required: "function" (string), "x_range" ([min, max]), "y_range" ([min, max])
   - Optional: "area_range" ([a, b]) — the interval to shade under the curve
   - Shows shaded area under the curve.

WHITEBOARD BEHAVIOR — THIS IS THE MOST IMPORTANT SECTION:
The video works like a real whiteboard. Content ACCUMULATES on screen so the student can
see the full chain of reasoning at once, just like a tutor writing line by line on a board.

ACCUMULATION RULES:
- "write" adds a NEW LINE below everything already on the board. Prior lines STAY VISIBLE.
- "transform" replaces the BOTTOM-MOST line in-place. The student LOSES the old version.
- "highlight" adds a new line below and flashes key terms. Prior lines stay visible.
- "color_transform" replaces the bottom line in-place with colored terms.
- "step_label" WIPES the entire board (like erasing the whiteboard for a new section).
- "graph", "tangent", "area" WIPE the board for a full-screen diagram.

CRITICAL — USE "write" FOR SHOWING WORK, NOT "transform":
A student learns by seeing ALL the intermediate steps on screen simultaneously. When you
solve an equation, each algebraic step should be a "write" so it appears as a new line
BELOW the previous one. The student can look up and see how they got there.

BAD (student only sees one line at a time — previous work vanishes):
  write:     \\int (4x^3 + 2x)\\,dx
  transform: → \\int 4x^3\\,dx + \\int 2x\\,dx    ← REPLACES the line above!
  transform: → x^4 + x^2 + C                        ← REPLACES again!

GOOD (student sees the full derivation building up line by line):
  write: \\int (4x^3 + 2x)\\,dx
  write: = \\int 4x^3\\,dx + \\int 2x\\,dx          ← new line below
  write: = 4 \\cdot \\frac{x^4}{4} + 2 \\cdot \\frac{x^2}{2} + C   ← new line below
  write: = x^4 + x^2 + C                             ← new line below

Use "transform" ONLY for tiny in-place simplifications where keeping the old version
would add clutter (e.g. cancelling a coefficient: 4·x⁴/4 → x⁴). If in doubt, use "write".

FLOW PATTERN:
  step_label → write → write → write → write (3-5 lines accumulate, student sees full work)
  step_label → write → write → transform (only final simplification replaces)
  graph or tangent (wipe for full-screen diagram)
  write → highlight (final answer ON THE SAME PAGE as the last equation steps!)

Use "step_label" every 3-5 equation lines to wipe the board and start fresh,
preventing the board from getting too crowded.

FINAL ANSWER — KEEP IT ON THE SAME PAGE:
Do NOT put a step_label before the final answer. The student should see the last
few derivation steps AND the boxed final answer on the same whiteboard. Use a "highlight"
as the very last step — it will appear below the accumulated equations.

VISUAL FLOW WITH ARROWS AND ANNOTATIONS:
Use LaTeX arrows and annotations to show logical connections between steps:
- Use \\Rightarrow to show "therefore" or "which gives us"
- Use \\xrightarrow{\\text{power rule}} for labeled arrows explaining the technique
- Use \\underbrace{...}_{\\text{...}} to annotate parts of expressions
- Use \\overset{\\text{simplify}}{=} instead of plain "=" to label what you're doing
- Example: "\\xrightarrow{\\text{sum rule}} \\int 4x^3\\,dx + \\int 2x\\,dx"
These visual cues help the student follow the logic, like a tutor drawing arrows on a board.

GUIDELINES FOR GOOD SOLUTIONS:
- Follow the step count specified in the VIDEO REQUIREMENTS section below. Show ALL your work —
  every algebraic manipulation should be visible. The student is here to understand, not just see an answer.
- Prefer "write" over "transform". Each "write" step builds on the previous line so the
  student sees the full chain of reasoning. Prefix continuation lines with "= " or
  "\\Rightarrow" so the student follows the logical flow.
- Use "step_label" to divide the solution into 2-3 sections. Each section should have
  3-5 equation steps that build on each other visually.

NARRATION STYLE — THIS IS A SPOKEN VOICE-OVER, NOT TEXT:
- Write narrations as if you're speaking to a student sitting next to you. Be warm and encouraging.
- Use conversational transitions between steps:
  Opening: "Alright, let's dive in!", "Okay, so here's what we're working with..."
  Building: "Now here's where it gets interesting...", "Stay with me on this one..."
  Revealing: "And look at that!", "See how that simplifies?", "Nice — that's much cleaner."
  Celebrating: "And there it is!", "Boom — that's our answer!", "Beautiful result."
- Name techniques when you use them: "This is the chain rule — we differentiate the outside,
  then multiply by the derivative of the inside."
- Briefly explain WHY each step works, not just WHAT you're doing.
- Add quick intuition checks: "Think of it this way...", "Notice how this makes sense because..."
- Keep narrations to 1-3 sentences. Avoid LaTeX notation — write everything as spoken words.
  Say "x squared" not "x^2", say "the square root of 3" not "sqrt(3)".
- IMPORTANT: Narrations appear as subtitles in the video. Keep each narration under 120 characters
  so it fits on screen without wrapping to tiny text.

VISUALS AND GRAPHS:
- Include at least TWO visual steps (graph, tangent, or area) for ANY problem that involves
  functions, derivatives, or integrals. Visuals are critical for learning. Place graph steps BETWEEN equation sections, not mid-algebra.
- Lean into visuals GENEROUSLY. If the problem involves a function, always include a graph.
  If it involves a derivative, show the tangent line. If it involves an integral, show the
  shaded area. Students learn better when they can SEE what's happening.
- Use "color_transform" at least once per solution to highlight different terms in distinct
  colors. This helps students see which parts of an expression correspond to which concepts.
- End with a "highlight" step showing the final answer in boxed format "\\boxed{...}".
  This MUST come directly after the last write steps — never after a step_label.
- All LaTeX must be valid and use standard notation (\\frac, \\sqrt, \\int, \\lim, etc.).
- Keep each LaTeX expression under 60 chars so it fits on one line of the whiteboard."""


def generate_solution(question_text: str, preferences: str = "", chat_context: str = "",
                      preset: str = None, active_overrides: list = None, progress_cb=None) -> dict:
    """Generate a step-by-step math solution using GPT-5.3.

    Args:
        question_text: The math problem to solve (plain text or LaTeX).
        preferences: Optional student preferences from mem0
                     (e.g. "- Include more graphs\n- Simpler language").
                     Injected into the system prompt to personalise output.
        chat_context: Optional recent chat messages for conversational context.
        preset: Video style preset — "quick_review", "standard", or "deep_dive".
        active_overrides: List of active override keys (e.g. ["more_graphs", "more_color"]).

    Returns:
        A dict with keys 'title', 'problem_latex', and 'steps',
        validated against the expected schema.

    Raises:
        ValueError: If the response fails validation.
        openai.APIError: If the API call fails.
    """
    # Build system prompt — inject structured video requirements
    system = SYSTEM_PROMPT

    # Build structured video requirements from preset + overrides
    from memory import build_video_requirements
    video_reqs = build_video_requirements(preset, active_overrides)
    system += "\n\n" + video_reqs

    if preferences or chat_context:
        system += "\n\nABOUT THIS STUDENT:\n"
        if preferences:
            system += "Student profile (from memory):\n" + preferences + "\n"
        if chat_context:
            system += chat_context + "\n"

    last_error = None
    for attempt in range(3):  # 3 attempts instead of 2
        try:
            response = client.chat.completions.create(
                model="gpt-5.3-chat-latest",
                max_completion_tokens=4096,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": question_text},
                ]
            )

            raw_text = response.choices[0].message.content

            # Try parsing the response as JSON directly
            try:
                result = json.loads(raw_text)
            except json.JSONDecodeError:
                # If direct parsing fails, try to extract JSON from the response
                # by finding the outermost { ... } pair
                start = raw_text.find("{")
                end = raw_text.rfind("}")
                if start == -1 or end == -1 or end <= start:
                    last_error = ValueError(
                        f"GPT did not return valid JSON. Response was:\n{raw_text[:500]}"
                    )
                    continue
                extracted = raw_text[start:end + 1]
                try:
                    result = json.loads(extracted)
                except json.JSONDecodeError as e:
                    last_error = ValueError(
                        f"Could not parse extracted JSON: {e}\nExtracted text:\n{extracted[:500]}"
                    )
                    continue

            try:
                _validate(result)
                return result
            except ValueError as e:
                last_error = e
                continue

        except Exception as api_err:
            last_error = api_err
            logging.error("AI solver API error (attempt %d): %s", attempt + 1, api_err)
            continue

    raise last_error


def _validate(data: dict):
    """Validate that the solution dict matches the expected schema.

    Args:
        data: The parsed JSON dict to validate.

    Raises:
        ValueError: If any required fields are missing or malformed.
    """
    # Top-level required fields
    if "title" not in data:
        raise ValueError("Missing required field: 'title'")
    if "problem_latex" not in data:
        raise ValueError("Missing required field: 'problem_latex'")
    if "steps" not in data:
        raise ValueError("Missing required field: 'steps'")

    if not isinstance(data["steps"], list) or len(data["steps"]) == 0:
        raise ValueError("'steps' must be a non-empty list")

    # Animation-specific required fields
    animation_fields = {
        "step_label": ["label"],
        "write": ["latex"],
        "transform": ["latex_from", "latex_to"],
        "highlight": ["latex", "highlight_terms"],
        "color_transform": ["latex_to", "colors"],
        "graph": ["function", "x_range", "y_range"],
        "tangent": ["function", "x_point", "x_range", "y_range"],
        "area": ["function", "x_range", "y_range"],
    }

    for i, step in enumerate(data["steps"]):
        if "animation" not in step:
            raise ValueError(f"Step {i}: missing required field 'animation'")
        # Auto-fill missing narration instead of crashing — LLMs occasionally omit it
        if "narration" not in step:
            step["narration"] = ""

        anim_type = step["animation"]
        if anim_type not in animation_fields:
            raise ValueError(
                f"Step {i}: unknown animation type '{anim_type}'. "
                f"Valid types: {list(animation_fields.keys())}"
            )

        required = animation_fields[anim_type]
        for field in required:
            if field not in step:
                raise ValueError(
                    f"Step {i} (animation '{anim_type}'): "
                    f"missing required field '{field}'"
                )


def _safe_eval(expr: str, x: float) -> float:
    """Safely evaluate a math expression with a given x value.

    Only allows basic math functions — no access to builtins, imports,
    or filesystem.

    Args:
        expr: A Python math expression using variable x
              (e.g., "x**3 - 2*x + 1").
        x: The value to substitute for x.

    Returns:
        The numerical result of evaluating the expression.

    Raises:
        Exception: If the expression is invalid or uses disallowed constructs.
    """
    restricted_globals = {
        "__builtins__": {"__import__": None, "abs": abs, "round": round, "min": min, "max": max},
        "x": x,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "sqrt": math.sqrt,
        "pi": math.pi,
        "e": math.e,
        "abs": abs,
        "log": math.log,
        "exp": math.exp,
    }
    try:
        return eval(expr, restricted_globals)
    except Exception:
        return 0.0


# Alias for server.py imports
TUTOR_PERSONALITY = SYSTEM_PROMPT
