import os
import json
from manim import *
from animations import (
    write_step, transform_step, highlight_step,
    color_transform_step, graph_step, tangent_step,
    area_step, step_label_step, diagram_step,
    number_line_step, annotated_graph_step, BOARD_TOP,
    SUBTITLE_FONT, FADE_OUT_TIME, MAX_SUBTITLE_WIDTH,
)

DISPATCH = {
    "write": write_step,
    "transform": transform_step,
    "highlight": highlight_step,
    "color_transform": color_transform_step,
    "graph": graph_step,
    "tangent": tangent_step,
    "area": area_step,
    "step_label": step_label_step,
    "diagram": diagram_step,
    "number_line": number_line_step,
    "annotated_graph": annotated_graph_step,
}


def _load_question():
    """Load question data.

    Priority:
      1. QUESTION_FILE env var  — path to a JSON file that IS the question object.
      2. QUESTION_ID  env var   — look up by id in questions.json (legacy).
    """
    # --- Option 1: direct file path (pipeline per-job rendering) ---
    qfile = os.environ.get("QUESTION_FILE")
    if qfile:
        with open(qfile, "r") as f:
            return json.load(f)

    # --- Option 2: lookup by id in questions.json ---
    qid = os.environ.get("QUESTION_ID")
    if not qid:
        raise RuntimeError(
            "Set QUESTION_FILE or QUESTION_ID. Run via generate.py."
        )
    with open("questions.json", "r") as f:
        bank = json.load(f)
    for q in bank["questions"]:
        if q["id"] == qid:
            return q
    raise RuntimeError(f"Question '{qid}' not found in questions.json")


class TutorialScene(Scene):
    def construct(self):
        question = _load_question()

        # White whiteboard background
        self.camera.background_color = "#ffffff"

        # --- Title card ---
        title = Text(question["title"], font_size=36, color=BLACK).to_edge(UP)
        problem = MathTex(question["problem_latex"], font_size=42, color=BLACK)

        # Show narration as subtitle (safe width scaling)
        first_step = question["steps"][0]
        subtitle = Text(first_step["narration"], font_size=SUBTITLE_FONT, color="#444444")
        if subtitle.width > MAX_SUBTITLE_WIDTH:
            subtitle.scale_to_fit_width(MAX_SUBTITLE_WIDTH)
        subtitle.to_edge(DOWN, buff=0.4)

        narration_dur = first_step.get("narration_duration", 0)
        self.play(Write(title), run_time=1)
        self.play(Write(problem), FadeIn(subtitle), run_time=2)
        # Sync with TTS: wait for remaining narration time
        # The FadeOut below takes 0.3s and is included in the narration window
        clear_time = 0.3  # FadeOut run_time below
        elapsed = 1 + 2  # title write + problem write
        if narration_dur > 0:
            remaining = narration_dur - elapsed - clear_time
            self.wait(max(remaining, 0.3))
        else:
            self.wait(1)

        # Clear the title card (time is already accounted for above)
        self.play(FadeOut(title), FadeOut(problem), FadeOut(subtitle), run_time=0.3)

        # --- Whiteboard: process steps with accumulating board context ---
        board = {
            "items": [],       # list of mobjects currently on screen
            "next_y": BOARD_TOP,  # y-coordinate for the next line
        }

        for step in question["steps"][1:]:
            anim_type = step.get("animation", "write")
            handler = DISPATCH.get(anim_type, write_step)
            handler(self, step, board)

        # Final pause
        self.wait(2)
