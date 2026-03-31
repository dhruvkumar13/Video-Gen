from manim import *
import math

# Duration constants (seconds)
WRITE_TIME = 2.0
TRANSFORM_TIME = 2.5
GRAPH_TIME = 2.0
MAX_SUBTITLE_WIDTH = 12
SUBTITLE_FONT = 24         # caption font size (larger for readability)
FADE_OUT_TIME = 0.3        # seconds to fade subtitle out

# Board layout constants
BOARD_TOP = 2.5        # y-coordinate of the first equation line
BOARD_BOTTOM = -2.0    # if next_y drops below this, board is "full"
LINE_SPACING = 0.85    # vertical gap between stacked equations
EQUATION_FONT = 42     # font size for board equations (slightly smaller to fit more)
EQUATION_COLOR = BLACK  # default text/equation color for whiteboard look

# Restricted namespace for safe expression evaluation
# Python 3.14 requires __import__ in builtins even for basic eval; set to None to block it safely
_SAFE_BUILTINS = {"__import__": None, "abs": abs, "round": round, "min": min, "max": max}
_SAFE_GLOBALS = {
    "__builtins__": _SAFE_BUILTINS,
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


def _safe_eval(expr, x):
    """Evaluate a math expression string with only safe math operations."""
    local_vars = {"x": x}
    try:
        return float(eval(expr, _SAFE_GLOBALS, local_vars))
    except Exception:
        return 0.0


def _make_subtitle(text):
    """Create a subtitle Text mobject with consistent styling.

    Avoids the Manim bug where passing width= to Text() forces a rescale
    that overrides font_size. Instead, creates at the desired font_size
    and only scales down if the result is wider than MAX_SUBTITLE_WIDTH.
    """
    subtitle = Text(text, font_size=SUBTITLE_FONT, color="#333333")
    if subtitle.width > MAX_SUBTITLE_WIDTH:
        subtitle.scale_to_fit_width(MAX_SUBTITLE_WIDTH)
    subtitle.to_edge(DOWN, buff=0.4)
    return subtitle


def _narration_wait(scene, step, elapsed):
    """Wait long enough for the subtitle to stay on-screen for the full TTS duration.

    Args:
        scene: The Manim scene.
        step: The step dict (may contain 'narration_duration' from TTS).
        elapsed: Seconds already consumed by animations before this wait.

    The subtitle should remain visible for the entire narration audio.
    We subtract what's already played (animations) and the upcoming fade-out,
    then wait the remaining time so the two stay in sync.
    """
    narration_dur = step.get("narration_duration", 0)
    if narration_dur > 0:
        remaining = narration_dur - elapsed - FADE_OUT_TIME
        if remaining > 0.1:
            scene.wait(remaining)
        else:
            scene.wait(0.3)  # minimum breathing room
    else:
        # Fallback when no TTS duration is available
        scene.wait(0.8)


def _clear_board(scene, board):
    """Fade out all items on the board and reset cursor position. Returns time consumed."""
    elapsed = 0.0
    if board["items"]:
        scene.play(
            *[FadeOut(item) for item in board["items"]],
            run_time=0.4,
        )
        elapsed = 0.4
    board["items"] = []
    board["next_y"] = BOARD_TOP
    return elapsed


def _place_on_board(mobject, board):
    """Position a mobject at the current board cursor and advance the cursor."""
    mobject.move_to(UP * board["next_y"])
    board["items"].append(mobject)
    board["next_y"] -= (mobject.height + LINE_SPACING)


def _scroll_if_needed(scene, board):
    """If the board cursor is past the bottom, scroll everything up. Returns time consumed."""
    if board["next_y"] >= BOARD_BOTTOM:
        return 0.0  # still room

    # Calculate how much to shift up
    overshoot = BOARD_BOTTOM - board["next_y"] + LINE_SPACING
    shift = UP * overshoot

    # Animate all board items scrolling up
    scene.play(
        *[item.animate.shift(shift) for item in board["items"]],
        run_time=0.5,
    )
    board["next_y"] += overshoot
    return 0.5


# ---------------------------------------------------------------------------
# 1. write_step  —  adds a new equation below existing content
# ---------------------------------------------------------------------------

def write_step(scene, step, board):
    """Write new LaTeX on the whiteboard below existing content."""
    new_tex = MathTex(step["latex"], font_size=EQUATION_FONT, color=EQUATION_COLOR)
    subtitle = _make_subtitle(step["narration"])

    scroll_time = _scroll_if_needed(scene, board)
    _place_on_board(new_tex, board)

    scene.play(Write(new_tex), FadeIn(subtitle), run_time=WRITE_TIME)
    _narration_wait(scene, step, elapsed=scroll_time + WRITE_TIME)
    scene.play(FadeOut(subtitle), run_time=FADE_OUT_TIME)


# ---------------------------------------------------------------------------
# 2. transform_step  —  morphs the BOTTOM equation in place
# ---------------------------------------------------------------------------

def transform_step(scene, step, board):
    """Transform the most recent equation into a new one, keeping position."""
    new_tex = MathTex(step["latex_to"], font_size=EQUATION_FONT, color=EQUATION_COLOR)
    subtitle = _make_subtitle(step["narration"])

    if board["items"]:
        # Morph the last item on the board
        old_tex = board["items"][-1]
        new_tex.move_to(old_tex.get_center())

        scene.play(FadeIn(subtitle), run_time=0.3)
        scene.play(Indicate(old_tex, color="#e74c3c"), run_time=0.6)
        scene.play(
            TransformMatchingTex(old_tex, new_tex),
            run_time=TRANSFORM_TIME,
        )
        # Replace reference in board items
        board["items"][-1] = new_tex
        _narration_wait(scene, step, elapsed=0.3 + 0.6 + TRANSFORM_TIME)
        scene.play(FadeOut(subtitle), run_time=FADE_OUT_TIME)
    else:
        # Nothing on board yet, just write it
        _place_on_board(new_tex, board)
        scene.play(Write(new_tex), FadeIn(subtitle), run_time=WRITE_TIME)
        _narration_wait(scene, step, elapsed=WRITE_TIME)
        scene.play(FadeOut(subtitle), run_time=FADE_OUT_TIME)


# ---------------------------------------------------------------------------
# 3. highlight_step  —  adds equation below, then flashes key terms
# ---------------------------------------------------------------------------

def highlight_step(scene, step, board):
    """Write LaTeX on the board then highlight specific terms."""
    tex = MathTex(step["latex"], font_size=EQUATION_FONT, color=EQUATION_COLOR)
    subtitle = _make_subtitle(step["narration"])

    scroll_time = _scroll_if_needed(scene, board)
    _place_on_board(tex, board)

    scene.play(Write(tex), FadeIn(subtitle), run_time=WRITE_TIME)
    elapsed = scroll_time + WRITE_TIME

    highlight_terms = step.get("highlight_terms", [])
    for term in highlight_terms:
        # Try matching against submobjects
        for sub in tex.submobjects:
            if hasattr(sub, "get_tex_string") and sub.get_tex_string() == term:
                scene.play(Circumscribe(sub, color=RED, run_time=0.8))
                elapsed += 0.8
                break
        else:
            # Fallback: highlight the whole tex if no submob match
            scene.play(Circumscribe(tex, color=RED, run_time=0.8))
            elapsed += 0.8

    _narration_wait(scene, step, elapsed=elapsed)
    scene.play(FadeOut(subtitle), run_time=FADE_OUT_TIME)


# ---------------------------------------------------------------------------
# 4. color_transform_step  —  morphs bottom equation with color coding
# ---------------------------------------------------------------------------

def color_transform_step(scene, step, board):
    """Transform the most recent equation with color-coded terms."""
    new_tex = MathTex(step["latex_to"], font_size=EQUATION_FONT, color=EQUATION_COLOR)
    subtitle = _make_subtitle(step["narration"])

    colors = step.get("colors", {})
    for tex_str, hex_color in colors.items():
        new_tex.set_color_by_tex(tex_str, hex_color)

    if board["items"]:
        old_tex = board["items"][-1]
        new_tex.move_to(old_tex.get_center())

        scene.play(FadeIn(subtitle), run_time=0.3)
        scene.play(Indicate(old_tex, color="#e74c3c"), run_time=0.6)
        scene.play(
            TransformMatchingTex(old_tex, new_tex),
            run_time=TRANSFORM_TIME,
        )
        board["items"][-1] = new_tex
        _narration_wait(scene, step, elapsed=0.3 + 0.6 + TRANSFORM_TIME)
        scene.play(FadeOut(subtitle), run_time=FADE_OUT_TIME)
    else:
        _place_on_board(new_tex, board)
        scene.play(Write(new_tex), FadeIn(subtitle), run_time=WRITE_TIME)
        _narration_wait(scene, step, elapsed=WRITE_TIME)
        scene.play(FadeOut(subtitle), run_time=FADE_OUT_TIME)


# ---------------------------------------------------------------------------
# 5. graph_step  —  wipes board, shows full-screen plot
# ---------------------------------------------------------------------------

def graph_step(scene, step, board):
    """Clear the board and plot a function on full-screen axes."""
    clear_time = _clear_board(scene, board)
    subtitle = _make_subtitle(step["narration"])

    axes = Axes(
        x_range=step["x_range"],
        y_range=step["y_range"],
        axis_config={"include_numbers": True, "color": "#333333"},
    ).scale(0.85)

    expr = step["function"]
    graph = axes.plot(lambda x: _safe_eval(expr, x), color=BLUE)
    group = VGroup(axes, graph)

    scene.play(Create(axes), FadeIn(subtitle), run_time=GRAPH_TIME)
    scene.play(Create(graph), run_time=GRAPH_TIME)
    _narration_wait(scene, step, elapsed=clear_time + GRAPH_TIME + GRAPH_TIME)
    scene.play(FadeOut(subtitle), run_time=FADE_OUT_TIME)

    # Store graph group so next step_label can clear it
    board["items"] = [group]
    board["next_y"] = BOARD_TOP  # reset for next text section


# ---------------------------------------------------------------------------
# 6. tangent_step  —  wipes board, shows curve + tangent line
# ---------------------------------------------------------------------------

def tangent_step(scene, step, board):
    """Clear the board and show a function with tangent line at a point."""
    clear_time = _clear_board(scene, board)
    subtitle = _make_subtitle(step["narration"])

    axes = Axes(
        x_range=step["x_range"],
        y_range=step["y_range"],
        axis_config={"include_numbers": True, "color": "#333333"},
    ).scale(0.85)

    expr = step["function"]
    graph = axes.plot(lambda x: _safe_eval(expr, x), color=BLUE)

    # Compute tangent via symmetric difference quotient
    x0 = step["x_point"]
    h = 0.001
    y0 = _safe_eval(expr, x0)
    slope = (_safe_eval(expr, x0 + h) - _safe_eval(expr, x0 - h)) / (2 * h)

    dx = 1.5
    tangent_line = Line(
        axes.c2p(x0 - dx, y0 + slope * (-dx)),
        axes.c2p(x0 + dx, y0 + slope * dx),
        color="#e74c3c",
        stroke_width=3,
    )
    dot = Dot(axes.c2p(x0, y0), color=RED, radius=0.08)

    group = VGroup(axes, graph, tangent_line, dot)

    scene.play(Create(axes), FadeIn(subtitle), run_time=GRAPH_TIME)
    scene.play(Create(graph), run_time=GRAPH_TIME)
    scene.play(Create(tangent_line), FadeIn(dot), run_time=1.0)
    _narration_wait(scene, step, elapsed=clear_time + GRAPH_TIME + GRAPH_TIME + 1.0)
    scene.play(FadeOut(subtitle), run_time=FADE_OUT_TIME)

    board["items"] = [group]
    board["next_y"] = BOARD_TOP


# ---------------------------------------------------------------------------
# 7. area_step  —  wipes board, shows curve + shaded area
# ---------------------------------------------------------------------------

def area_step(scene, step, board):
    """Clear the board and show a function with shaded area underneath."""
    clear_time = _clear_board(scene, board)
    subtitle = _make_subtitle(step["narration"])

    axes = Axes(
        x_range=step["x_range"],
        y_range=step["y_range"],
        axis_config={"include_numbers": True, "color": "#333333"},
    ).scale(0.85)

    expr = step["function"]
    graph = axes.plot(lambda x: _safe_eval(expr, x), color=BLUE)

    area_range = step.get("area_range", step["x_range"][:2])
    area = axes.get_area(graph, x_range=area_range, color=BLUE, opacity=0.3)

    group = VGroup(axes, graph, area)

    scene.play(Create(axes), FadeIn(subtitle), run_time=GRAPH_TIME)
    scene.play(Create(graph), run_time=GRAPH_TIME)
    scene.play(FadeIn(area), run_time=1.0)
    _narration_wait(scene, step, elapsed=clear_time + GRAPH_TIME + GRAPH_TIME + 1.0)
    scene.play(FadeOut(subtitle), run_time=FADE_OUT_TIME)

    board["items"] = [group]
    board["next_y"] = BOARD_TOP


# ---------------------------------------------------------------------------
# 8. step_label_step  —  WIPES the board, shows section header
# ---------------------------------------------------------------------------

def step_label_step(scene, step, board):
    """Wipe the whiteboard clean, show a section label, then clear it."""
    clear_time = _clear_board(scene, board)

    label = Text(step["label"], font_size=36, color=BLACK)
    subtitle = _make_subtitle(step["narration"])

    scene.play(FadeIn(label), FadeIn(subtitle), run_time=0.8)
    _narration_wait(scene, step, elapsed=clear_time + 0.8)
    scene.play(FadeOut(label), FadeOut(subtitle), run_time=0.6)

    # Board is now empty, ready for new content
    board["items"] = []
    board["next_y"] = BOARD_TOP


# ---------------------------------------------------------------------------
# 9. diagram_step  —  wipes board, shows geometric diagram with shapes
# ---------------------------------------------------------------------------

def diagram_step(scene, step, board):
    """Clear the board and display a geometric diagram with labeled shapes."""
    clear_time = _clear_board(scene, board)
    subtitle = _make_subtitle(step["narration"])

    shapes_data = step.get("shapes", [])
    all_mobjects = VGroup()
    labels = VGroup()

    # Optional title above the diagram
    title_text = step.get("title", "")
    if title_text:
        title = Text(title_text, font_size=32, color=BLACK)
        title.to_edge(UP, buff=0.5)
        all_mobjects.add(title)

    for shape_info in shapes_data:
        shape_type = shape_info.get("type", "point")
        pos = shape_info.get("position", [0, 0])
        color = shape_info.get("color", "#58a6ff")
        size = shape_info.get("size", 1.0)
        label_text = shape_info.get("label", "")

        mob = None
        label_pos = None

        if shape_type == "circle":
            mob = Circle(radius=size * 0.5, color=color, stroke_width=3)
            mob.move_to([pos[0], pos[1], 0])
            label_pos = mob.get_center() + DOWN * (size * 0.5 + 0.3)

        elif shape_type == "rectangle":
            mob = Rectangle(width=size, height=size * 0.7, color=color, stroke_width=3)
            mob.move_to([pos[0], pos[1], 0])
            label_pos = mob.get_bottom() + DOWN * 0.3

        elif shape_type == "triangle":
            mob = Triangle(color=color, stroke_width=3)
            mob.scale(size * 0.5)
            mob.move_to([pos[0], pos[1], 0])
            label_pos = mob.get_bottom() + DOWN * 0.3

        elif shape_type == "line":
            if isinstance(pos[0], (list, tuple)):
                start_pt = [pos[0][0], pos[0][1], 0]
                end_pt = [pos[1][0], pos[1][1], 0]
            else:
                start_pt = [pos[0], pos[1], 0]
                end_pt = [pos[0] + size, pos[1], 0]
            mob = Line(start_pt, end_pt, color=color, stroke_width=3)
            label_pos = mob.get_center() + UP * 0.3

        elif shape_type == "arrow":
            if isinstance(pos[0], (list, tuple)):
                start_pt = [pos[0][0], pos[0][1], 0]
                end_pt = [pos[1][0], pos[1][1], 0]
            else:
                start_pt = [pos[0], pos[1], 0]
                end_pt = [pos[0] + size, pos[1], 0]
            mob = Arrow(start_pt, end_pt, color=color, stroke_width=3, buff=0)
            label_pos = mob.get_center() + UP * 0.3

        elif shape_type == "point":
            mob = Dot([pos[0], pos[1], 0], color=color, radius=0.08)
            label_pos = mob.get_center() + UP * 0.3

        if mob is not None:
            all_mobjects.add(mob)
            if label_text:
                lbl = Text(label_text, font_size=24, color=BLACK)
                lbl.move_to(label_pos)
                labels.add(lbl)

    # Scale entire diagram to fit the visible frame
    full_group = VGroup(all_mobjects, labels)
    if full_group.width > 10 or full_group.height > 5:
        full_group.scale_to_fit_width(min(full_group.width, 10))
        if full_group.height > 5:
            full_group.scale_to_fit_height(5)
    full_group.center()

    # Shift down a bit if there's a title
    if title_text:
        full_group.shift(DOWN * 0.3)

    scene.play(Create(all_mobjects), FadeIn(subtitle), run_time=GRAPH_TIME)
    scene.play(FadeIn(labels), run_time=0.8)
    _narration_wait(scene, step, elapsed=clear_time + GRAPH_TIME + 0.8)
    scene.play(FadeOut(subtitle), run_time=FADE_OUT_TIME)

    board["items"] = [full_group]
    board["next_y"] = BOARD_TOP


# ---------------------------------------------------------------------------
# 10. number_line_step  —  wipes board, shows number line with points/intervals
# ---------------------------------------------------------------------------

def number_line_step(scene, step, board):
    """Clear the board and display a number line with points and intervals."""
    clear_time = _clear_board(scene, board)
    subtitle = _make_subtitle(step["narration"])

    nl_range = step.get("range", [-5, 5])
    points_data = step.get("points", [])
    intervals_data = step.get("intervals", [])

    # Optional title
    title_text = step.get("title", "")
    all_mobjects = VGroup()

    if title_text:
        title = Text(title_text, font_size=32, color=BLACK)
        title.to_edge(UP, buff=0.5)
        all_mobjects.add(title)

    # Create the number line
    number_line = NumberLine(
        x_range=[nl_range[0], nl_range[1], 1],
        length=10,
        include_numbers=True,
        color="#333333",
    )
    all_mobjects.add(number_line)

    interval_mobs = VGroup()
    for interval in intervals_data:
        i_from = interval.get("from", nl_range[0])
        i_to = interval.get("to", nl_range[1])
        i_color = interval.get("color", "#4ecdc4")
        line_seg = Line(
            number_line.n2p(i_from),
            number_line.n2p(i_to),
            color=i_color,
            stroke_width=8,
        )
        interval_mobs.add(line_seg)

    point_mobs = VGroup()
    point_labels = VGroup()
    for pt in points_data:
        val = pt.get("value", 0)
        style = pt.get("style", "closed")
        label_text_pt = pt.get("label", str(val))
        pos = number_line.n2p(val)

        if style == "closed":
            dot = Dot(pos, color="#e74c3c", radius=0.12)
            point_mobs.add(dot)
        elif style == "open":
            ring = Circle(radius=0.12, color="#e74c3c", stroke_width=3)
            ring.set_fill(WHITE, opacity=1)
            ring.move_to(pos)
            point_mobs.add(ring)
        elif style == "arrow_right":
            arr = Arrow(pos, pos + RIGHT * 1.5, color="#e74c3c", buff=0)
            point_mobs.add(arr)
        elif style == "arrow_left":
            arr = Arrow(pos, pos + LEFT * 1.5, color="#e74c3c", buff=0)
            point_mobs.add(arr)

        if label_text_pt:
            lbl = Text(label_text_pt, font_size=22, color=BLACK)
            lbl.next_to(pos, UP, buff=0.3)
            point_labels.add(lbl)

    scene.play(Create(number_line), FadeIn(subtitle), run_time=GRAPH_TIME)
    elapsed = clear_time + GRAPH_TIME

    if title_text:
        scene.play(FadeIn(all_mobjects[0]), run_time=0.5)
        elapsed += 0.5

    if interval_mobs:
        scene.play(Create(interval_mobs), run_time=0.8)
        elapsed += 0.8

    scene.play(FadeIn(point_mobs), FadeIn(point_labels), run_time=0.8)
    elapsed += 0.8

    _narration_wait(scene, step, elapsed=elapsed)
    scene.play(FadeOut(subtitle), run_time=FADE_OUT_TIME)

    group = VGroup(all_mobjects, interval_mobs, point_mobs, point_labels)
    board["items"] = [group]
    board["next_y"] = BOARD_TOP


# ---------------------------------------------------------------------------
# 11. annotated_graph_step  —  wipes board, shows graph with annotations
# ---------------------------------------------------------------------------

def annotated_graph_step(scene, step, board):
    """Clear the board and show a function graph with labeled annotations."""
    clear_time = _clear_board(scene, board)
    subtitle = _make_subtitle(step["narration"])

    axes = Axes(
        x_range=step["x_range"],
        y_range=step["y_range"],
        axis_config={"include_numbers": True, "color": "#333333"},
    ).scale(0.85)

    expr = step["function"]
    graph = axes.plot(lambda x: _safe_eval(expr, x), color=BLUE)

    group = VGroup(axes, graph)

    # Optional secondary function
    secondary_expr = step.get("secondary_function")
    secondary_graph = None
    if secondary_expr:
        secondary_graph = axes.plot(
            lambda x: _safe_eval(secondary_expr, x), color=RED
        )
        group.add(secondary_graph)

    scene.play(Create(axes), FadeIn(subtitle), run_time=GRAPH_TIME)
    scene.play(Create(graph), run_time=GRAPH_TIME)
    elapsed = clear_time + GRAPH_TIME + GRAPH_TIME

    if secondary_graph:
        scene.play(Create(secondary_graph), run_time=GRAPH_TIME)
        elapsed += GRAPH_TIME

    # Annotations
    annotations = step.get("annotations", [])
    for ann in annotations:
        x_val = ann.get("x", 0)
        label_text = ann.get("label", "")
        style = ann.get("style", "dot")

        try:
            y_val = _safe_eval(expr, x_val)
        except Exception:
            y_val = 0

        point_on_graph = axes.c2p(x_val, y_val)
        ann_group = VGroup()

        if style == "dot":
            dot = Dot(point_on_graph, color="#e74c3c", radius=0.08)
            ann_group.add(dot)
            if label_text:
                lbl = Text(label_text, font_size=20, color=BLACK)
                lbl.next_to(dot, UP, buff=0.2)
                ann_group.add(lbl)

        elif style == "arrow_up":
            dot = Dot(point_on_graph, color="#e74c3c", radius=0.08)
            arr = Arrow(
                point_on_graph + UP * 0.8,
                point_on_graph + UP * 0.15,
                color="#e74c3c",
                buff=0,
                stroke_width=3,
            )
            ann_group.add(dot, arr)
            if label_text:
                lbl = Text(label_text, font_size=20, color=BLACK)
                lbl.next_to(arr, UP, buff=0.15)
                ann_group.add(lbl)

        elif style == "arrow_down":
            dot = Dot(point_on_graph, color="#e74c3c", radius=0.08)
            arr = Arrow(
                point_on_graph + DOWN * 0.8,
                point_on_graph + DOWN * 0.15,
                color="#e74c3c",
                buff=0,
                stroke_width=3,
            )
            ann_group.add(dot, arr)
            if label_text:
                lbl = Text(label_text, font_size=20, color=BLACK)
                lbl.next_to(arr, DOWN, buff=0.15)
                ann_group.add(lbl)

        elif style == "vertical_line":
            top_pt = axes.c2p(x_val, step["y_range"][1])
            bot_pt = axes.c2p(x_val, step["y_range"][0])
            dashed = DashedLine(bot_pt, top_pt, color="#999999", stroke_width=2)
            ann_group.add(dashed)
            if label_text:
                lbl = Text(label_text, font_size=20, color=BLACK)
                lbl.next_to(dashed, UP, buff=0.15)
                ann_group.add(lbl)

        if ann_group:
            scene.play(FadeIn(ann_group), run_time=0.5)
            elapsed += 0.5
            group.add(ann_group)

    _narration_wait(scene, step, elapsed=elapsed)
    scene.play(FadeOut(subtitle), run_time=FADE_OUT_TIME)

    board["items"] = [group]
    board["next_y"] = BOARD_TOP
