import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { interpolate } from "remotion";
import "katex/dist/katex.min.css";
import { KaTeX } from "./components/KaTeX";
import { Graph } from "./components/Graph";
import { Diagram } from "./components/Diagram";
import { NumberLine } from "./components/NumberLine";
import { AnnotatedGraph } from "./components/AnnotatedGraph";

/* ═══════════════════════════════════════════════════════════
   Types — "animation" matches the JSON key from ai_solver.py
═══════════════════════════════════════════════════════════ */

export interface StepData {
  animation: string;
  latex?: string;
  latex_to?: string;
  narration: string;
  narration_duration?: number;   // seconds — from TTS audio measurement
  highlight_terms?: string[];
  colors?: Record<string, string>;
  function?: string;
  x_range?: number[];
  y_range?: number[];
  x_point?: number;
  area_range?: number[];
  label?: string;
  shapes?: Array<{type: string; position: number[] | number[][]; label?: string; color?: string; size?: number}>;
  range?: number[];
  points?: Array<{value: number; label: string; style: string}>;
  intervals?: Array<{from: number; to: number; color: string}>;
  annotations?: Array<{x: number; label: string; style: string}>;
  secondary_function?: string;
  title?: string;
}

export interface QuestionData {
  title: string;
  problem_latex: string;
  steps: StepData[];
}

/* ═══════════════════════════════════════════════════════════
   Timing — driven by TTS narration length when available
═══════════════════════════════════════════════════════════ */

const FPS = 30;

// Fallback durations (frames) when TTS timing is not available
const FALLBACK_DURATIONS: Record<string, number> = {
  title: 120,           // 4.0s
  write: 105,           // 3.5s
  transform: 90,        // 3.0s
  highlight: 120,       // 4.0s
  color_transform: 105, // 3.5s
  graph: 150,           // 5.0s
  tangent: 150,         // 5.0s
  area: 150,            // 5.0s
  step_label: 75,       // 2.5s
  diagram: 150,            // 5.0s
  number_line: 150,        // 5.0s
  annotated_graph: 180,    // 6.0s
};

// Minimum durations (frames) — ensure animations have time to play
const MIN_DURATIONS: Record<string, number> = {
  title: 90,            // 3.0s
  write: 60,            // 2.0s
  transform: 60,        // 2.0s
  highlight: 75,        // 2.5s
  color_transform: 60,  // 2.0s
  graph: 120,           // 4.0s
  tangent: 120,         // 4.0s
  area: 120,            // 4.0s
  step_label: 60,       // 2.0s
  diagram: 120,            // 4.0s
  number_line: 120,        // 4.0s
  annotated_graph: 120,    // 4.0s
};

const FINAL_PAUSE = 60; // 2.0s — hold final frame

/** Get duration in frames for a step, using TTS audio length when available. */
function getStepDuration(step: StepData): number {
  if (step.narration_duration && step.narration_duration > 0) {
    // Convert TTS seconds to frames, add a small pad for visual breathing room
    const audioFrames = Math.ceil(step.narration_duration * FPS) + 15;
    const minFrames = MIN_DURATIONS[step.animation] || 60;
    return Math.max(audioFrames, minFrames);
  }
  return FALLBACK_DURATIONS[step.animation] || 90;
}

export function calculateDuration(props: QuestionData): number {
  const steps = props.steps || [];
  // Title card consumes steps[0] — its narration_duration drives the title timing.
  // This matches Manim where scene.py uses steps[0] as the title subtitle and
  // dispatches steps[1:] to the whiteboard.
  const titleDur = steps.length > 0
    ? getStepDuration(steps[0])
    : FALLBACK_DURATIONS.title;

  let total = titleDur;
  for (let i = 1; i < steps.length; i++) {
    total += getStepDuration(steps[i]);
  }
  return total + FINAL_PAUSE;
}

/* ═══════════════════════════════════════════════════════════
   Board State (accumulated equations)
═══════════════════════════════════════════════════════════ */

interface BoardItem {
  latex: string;
  y: number;
  colors?: Record<string, string>;
}

const BOARD_TOP = 160;
const LINE_GAP = 70;

/** Replay steps 1..upTo-1 to compute the board state before step `upTo`.
 *  Starts from 1 because steps[0] is consumed by the title card. */
function computeBoard(steps: StepData[], upTo: number): BoardItem[] {
  const items: BoardItem[] = [];
  let nextY = BOARD_TOP;

  for (let i = 1; i < upTo; i++) {
    const s = steps[i];
    if (["step_label", "graph", "tangent", "area", "diagram", "number_line", "annotated_graph"].includes(s.animation)) {
      items.length = 0;
      nextY = BOARD_TOP;
      continue;
    }
    if (s.animation === "write" || s.animation === "highlight") {
      items.push({ latex: s.latex || "", y: nextY });
      nextY += LINE_GAP;
    } else if (s.animation === "transform" || s.animation === "color_transform") {
      if (items.length > 0) {
        items[items.length - 1] = {
          latex: s.latex_to || "",
          y: items[items.length - 1].y,
          colors: s.animation === "color_transform" ? s.colors : undefined,
        };
      } else {
        items.push({ latex: s.latex_to || "", y: nextY });
        nextY += LINE_GAP;
      }
    }
  }
  return items;
}

function nextYAfterBoard(board: BoardItem[]): number {
  if (board.length === 0) return BOARD_TOP;
  return board[board.length - 1].y + LINE_GAP;
}

/* ═══════════════════════════════════════════════════════════
   Phase Timeline
═══════════════════════════════════════════════════════════ */

interface Phase {
  kind: string;       // "title", "write", "transform", etc.
  step: StepData | null;
  index: number;      // step index (-1 for title)
  start: number;
  duration: number;
}

function buildTimeline(steps: StepData[]): Phase[] {
  const phases: Phase[] = [];
  let f = 0;

  // Title card consumes steps[0] (narration shown as subtitle, duration from TTS).
  // steps[0] is passed as the title's step so TitleCard can display its narration.
  const titleStep = steps.length > 0 ? steps[0] : null;
  const titleDur = titleStep
    ? getStepDuration(titleStep)
    : FALLBACK_DURATIONS.title;
  phases.push({ kind: "title", step: titleStep, index: 0, start: 0, duration: titleDur });
  f += titleDur;

  // Remaining steps start from index 1 (step[0] was consumed by the title card)
  for (let i = 1; i < steps.length; i++) {
    const dur = getStepDuration(steps[i]);
    phases.push({ kind: steps[i].animation, step: steps[i], index: i, start: f, duration: dur });
    f += dur;
  }
  return phases;
}

/* ═══════════════════════════════════════════════════════════
   MathScene (main composition)
═══════════════════════════════════════════════════════════ */

export const MathScene: React.FC<QuestionData> = (props) => {
  const frame = useCurrentFrame();
  const { title, problem_latex, steps } = props;

  const phases = buildTimeline(steps);

  // Find active phase
  let phaseIdx = 0;
  for (let i = phases.length - 1; i >= 0; i--) {
    if (frame >= phases[i].start) {
      phaseIdx = i;
      break;
    }
  }

  const phase = phases[phaseIdx];
  const local = frame - phase.start;

  return (
    <AbsoluteFill style={{ backgroundColor: "#ffffff" }}>
      {phase.kind === "title" && (
        <TitleCard
          title={title}
          latex={problem_latex}
          narration={phase.step?.narration || ""}
          frame={local}
          duration={phase.duration}
        />
      )}

      {phase.kind === "step_label" && phase.step && (
        <StepLabelView
          label={phase.step.label || ""}
          narration={phase.step.narration}
          frame={local}
          duration={phase.duration}
        />
      )}

      {["graph", "tangent", "area"].includes(phase.kind) && phase.step && (
        <GraphView step={phase.step} mode={phase.kind as any} frame={local} duration={phase.duration} />
      )}

      {phase.kind === "diagram" && phase.step && (
        <AbsoluteFill>
          <Diagram
            shapes={phase.step.shapes || []}
            title={phase.step.title}
            frame={local}
            duration={phase.duration}
          />
          <Subtitle text={phase.step.narration} frame={local} duration={phase.duration} />
        </AbsoluteFill>
      )}

      {phase.kind === "number_line" && phase.step && (
        <AbsoluteFill>
          <NumberLine
            range={phase.step.range || [-5, 5]}
            points={phase.step.points || []}
            intervals={phase.step.intervals}
            title={phase.step.title}
            frame={local}
            duration={phase.duration}
          />
          <Subtitle text={phase.step.narration} frame={local} duration={phase.duration} />
        </AbsoluteFill>
      )}

      {phase.kind === "annotated_graph" && phase.step && (
        <AbsoluteFill>
          <AnnotatedGraph
            fn={phase.step.function || "x"}
            xRange={phase.step.x_range || [-5, 5, 1]}
            yRange={phase.step.y_range || [-5, 5, 1]}
            annotations={phase.step.annotations || []}
            secondaryFn={phase.step.secondary_function}
            frame={local}
            duration={phase.duration}
          />
          <Subtitle text={phase.step.narration} frame={local} duration={phase.duration} />
        </AbsoluteFill>
      )}

      {["write", "transform", "highlight", "color_transform"].includes(phase.kind) && phase.step && (
        <BoardView
          steps={steps}
          stepIndex={phase.index}
          step={phase.step}
          frame={local}
          duration={phase.duration}
        />
      )}
    </AbsoluteFill>
  );
};

/* ═══════════════════════════════════════════════════════════
   Sub-views
═══════════════════════════════════════════════════════════ */

/* Title card — shows title + problem, with steps[0] narration as subtitle */
const TitleCard: React.FC<{
  title: string; latex: string; narration: string; frame: number; duration: number;
}> = ({ title, latex, narration, frame, duration }) => {
  const opacity = interpolate(
    frame,
    [0, 15, duration - 15, duration],
    [0, 1, 1, 0],
    { extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        opacity,
      }}
    >
      <div style={{ fontSize: 36, color: "#000", fontWeight: 600, marginBottom: 30 }}>
        {title}
      </div>
      <KaTeX latex={latex} fontSize={34} color="#000" />
      {narration && <Subtitle text={narration} frame={frame} duration={duration} />}
    </AbsoluteFill>
  );
};

/* Step label (section header) */
const StepLabelView: React.FC<{
  label: string; narration: string; frame: number; duration: number;
}> = ({ label, narration, frame, duration }) => {
  const opacity = interpolate(
    frame,
    [0, 12, duration - 12, duration],
    [0, 1, 1, 0],
    { extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <div style={{ fontSize: 32, color: "#000", fontWeight: 600, opacity }}>
        {label}
      </div>
      <Subtitle text={narration} frame={frame} duration={duration} />
    </AbsoluteFill>
  );
};

/* Graph / Tangent / Area view */
const GraphView: React.FC<{
  step: StepData; mode: "graph" | "tangent" | "area"; frame: number; duration: number;
}> = ({ step, mode, frame, duration }) => {
  return (
    <AbsoluteFill>
      <Graph
        fn={step.function || "x"}
        xRange={step.x_range || [-5, 5, 1]}
        yRange={step.y_range || [-5, 5, 1]}
        frame={frame}
        duration={duration}
        mode={mode}
        xPoint={step.x_point}
        areaRange={step.area_range}
      />
      <Subtitle text={step.narration} frame={frame} duration={duration} />
    </AbsoluteFill>
  );
};

/* Board view — accumulated equations + active step animation */
const BoardView: React.FC<{
  steps: StepData[];
  stepIndex: number;
  step: StepData;
  frame: number;
  duration: number;
}> = ({ steps, stepIndex, step, frame, duration }) => {
  // Get accumulated board state BEFORE this step
  const board = computeBoard(steps, stepIndex);
  const ny = nextYAfterBoard(board);

  // Active step animation — fade in over ~0.5s (15 frames at 30fps)
  const writeOpacity = interpolate(frame, [0, 18], [0, 1], { extrapolateRight: "clamp" });

  // For transform: crossfade from old to new over ~1s
  const isTransform = step.animation === "transform" || step.animation === "color_transform";
  const prevLatex = isTransform && board.length > 0 ? board[board.length - 1].latex : "";
  const transformProgress = interpolate(frame, [8, 38], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Highlight flash — gentle pulse
  const isHighlight = step.animation === "highlight";
  const highlightPulse = interpolate(
    frame,
    [25, 35, 45, 55],
    [1, 1.08, 1, 1.04],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // Remove the last board item if this is a transform (it will be animated)
  const displayBoard = isTransform && board.length > 0 ? board.slice(0, -1) : board;
  const transformY = isTransform && board.length > 0 ? board[board.length - 1].y : ny;

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      {/* Static accumulated items */}
      {displayBoard.map((item, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            top: item.y,
            left: "50%",
            transform: "translateX(-50%)",
          }}
        >
          <KaTeX latex={item.latex} fontSize={28} colorMap={item.colors} />
        </div>
      ))}

      {/* Active step */}
      {isTransform ? (
        /* Crossfade: old fades out, new fades in */
        <div style={{ position: "absolute", top: transformY, left: "50%", transform: "translateX(-50%)" }}>
          <div style={{ position: "absolute", opacity: 1 - transformProgress, left: "50%", transform: "translateX(-50%)" }}>
            <KaTeX latex={prevLatex} fontSize={28} />
          </div>
          <div style={{ opacity: transformProgress }}>
            <KaTeX
              latex={step.latex_to || ""}
              fontSize={28}
              colorMap={step.animation === "color_transform" ? step.colors : undefined}
            />
          </div>
        </div>
      ) : (
        /* Write / Highlight: fade in */
        <div
          style={{
            position: "absolute",
            top: ny,
            left: "50%",
            transform: `translateX(-50%) scale(${isHighlight ? highlightPulse : 1})`,
            opacity: writeOpacity,
          }}
        >
          <KaTeX latex={step.latex || ""} fontSize={28} />
        </div>
      )}

      {/* Subtitle */}
      <Subtitle text={step.narration} frame={frame} duration={duration} />
    </div>
  );
};

/* Subtitle — bottom narration text */
const Subtitle: React.FC<{ text: string; frame: number; duration: number }> = ({
  text,
  frame,
  duration,
}) => {
  const opacity = interpolate(
    frame,
    [0, 10, duration - 10, duration],
    [0, 1, 1, 0],
    { extrapolateRight: "clamp" }
  );

  return (
    <div
      style={{
        position: "absolute",
        bottom: 30,
        left: "50%",
        transform: "translateX(-50%)",
        fontSize: 30,
        color: "#444444",
        textAlign: "center",
        maxWidth: "85%",
        lineHeight: 1.45,
        fontWeight: 400,
        opacity,
      }}
    >
      {text}
    </div>
  );
};
