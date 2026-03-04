import React from "react";
import { interpolate } from "remotion";

interface AnnotationData {
  x: number;
  label: string;
  style: string;
}

interface AnnotatedGraphProps {
  fn: string;
  xRange: number[];
  yRange: number[];
  annotations: AnnotationData[];
  secondaryFn?: string;
  frame: number;
  duration: number;
}

// Safe math evaluation (duplicated from Graph.tsx)
function safeEval(expr: string, x: number): number {
  const ctx: Record<string, number | ((n: number) => number)> = {
    x,
    sin: Math.sin,
    cos: Math.cos,
    tan: Math.tan,
    sqrt: Math.sqrt,
    abs: Math.abs,
    log: Math.log,
    exp: Math.exp,
    pi: Math.PI,
    e: Math.E,
    PI: Math.PI,
    E: Math.E,
  };

  try {
    const fn = new Function(...Object.keys(ctx), `return (${expr});`);
    const val = fn(...Object.values(ctx));
    return typeof val === "number" && isFinite(val) ? val : 0;
  } catch {
    return 0;
  }
}

const SVG_W = 900;
const SVG_H = 500;
const PAD = 60;

function buildCurvePath(
  expr: string,
  xMin: number,
  xMax: number,
  yMin: number,
  yMax: number,
  toSvgX: (x: number) => number,
  toSvgY: (y: number) => number,
): string {
  const numPoints = 200;
  const pts: string[] = [];
  for (let i = 0; i <= numPoints; i++) {
    const x = xMin + (i / numPoints) * (xMax - xMin);
    const y = safeEval(expr, x);
    const clampedY = Math.max(yMin, Math.min(yMax, y));
    pts.push(`${toSvgX(x)},${toSvgY(clampedY)}`);
  }
  return "M " + pts.join(" L ");
}

export const AnnotatedGraph: React.FC<AnnotatedGraphProps> = ({
  fn,
  xRange,
  yRange,
  annotations,
  secondaryFn,
  frame,
  duration,
}) => {
  const [xMin, xMax] = xRange;
  const [yMin, yMax] = yRange;

  const toSvgX = (x: number) =>
    PAD + ((x - xMin) / (xMax - xMin)) * (SVG_W - 2 * PAD);
  const toSvgY = (y: number) =>
    SVG_H - PAD - ((y - yMin) / (yMax - yMin)) * (SVG_H - 2 * PAD);

  // Animation phases
  const axesOpacity = interpolate(frame, [0, 30], [0, 1], {
    extrapolateRight: "clamp",
  });
  const primaryProgress = interpolate(frame, [30, 90], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const secondaryProgress = interpolate(frame, [60, 90], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const pathLen = 2000;

  const primaryPath = buildCurvePath(fn, xMin, xMax, yMin, yMax, toSvgX, toSvgY);
  const secondaryPath = secondaryFn
    ? buildCurvePath(secondaryFn, xMin, xMax, yMin, yMax, toSvgX, toSvgY)
    : "";

  // Axis ticks
  const xTicks: number[] = [];
  for (let t = Math.ceil(xMin); t <= Math.floor(xMax); t++) {
    if (t !== 0) xTicks.push(t);
  }
  const yTicks: number[] = [];
  for (let t = Math.ceil(yMin); t <= Math.floor(yMax); t++) {
    if (t !== 0) yTicks.push(t);
  }

  const STAGGER = 15;
  const ANNO_START = 90;

  return (
    <div
      style={{
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        width: "100%",
        height: "100%",
      }}
    >
      <svg viewBox={`0 0 ${SVG_W} ${SVG_H}`} width={SVG_W} height={SVG_H}>
        {/* Axes */}
        <g opacity={axesOpacity}>
          <line
            x1={PAD}
            y1={toSvgY(0)}
            x2={SVG_W - PAD}
            y2={toSvgY(0)}
            stroke="#333333"
            strokeWidth={1.5}
          />
          <line
            x1={toSvgX(0)}
            y1={PAD}
            x2={toSvgX(0)}
            y2={SVG_H - PAD}
            stroke="#333333"
            strokeWidth={1.5}
          />
          {xTicks.map((t) => (
            <g key={`xt-${t}`}>
              <line
                x1={toSvgX(t)}
                y1={toSvgY(0) - 4}
                x2={toSvgX(t)}
                y2={toSvgY(0) + 4}
                stroke="#333"
                strokeWidth={1}
              />
              <text
                x={toSvgX(t)}
                y={toSvgY(0) + 18}
                textAnchor="middle"
                fontSize={12}
                fill="#555"
              >
                {t}
              </text>
            </g>
          ))}
          {yTicks.map((t) => (
            <g key={`yt-${t}`}>
              <line
                x1={toSvgX(0) - 4}
                y1={toSvgY(t)}
                x2={toSvgX(0) + 4}
                y2={toSvgY(t)}
                stroke="#333"
                strokeWidth={1}
              />
              <text
                x={toSvgX(0) - 10}
                y={toSvgY(t) + 4}
                textAnchor="end"
                fontSize={12}
                fill="#555"
              >
                {t}
              </text>
            </g>
          ))}
        </g>

        {/* Primary curve */}
        <path
          d={primaryPath}
          fill="none"
          stroke="#4285f4"
          strokeWidth={2.5}
          strokeDasharray={pathLen}
          strokeDashoffset={pathLen * (1 - primaryProgress)}
        />

        {/* Secondary curve */}
        {secondaryFn && secondaryPath && (
          <path
            d={secondaryPath}
            fill="none"
            stroke="#e74c3c"
            strokeWidth={2.5}
            strokeDasharray={pathLen}
            strokeDashoffset={pathLen * (1 - secondaryProgress)}
          />
        )}

        {/* Annotations */}
        {annotations.map((anno, i) => {
          const startFrame = ANNO_START + i * STAGGER;
          const opacity = interpolate(
            frame,
            [startFrame, startFrame + 20],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
          );

          const ax = toSvgX(anno.x);
          const ay = toSvgY(safeEval(fn, anno.x));

          switch (anno.style) {
            case "dot":
              return (
                <g key={`anno-${i}`} opacity={opacity}>
                  <circle cx={ax} cy={ay} r={6} fill="#e74c3c" />
                  <text
                    x={ax}
                    y={ay - 14}
                    textAnchor="middle"
                    fontSize={14}
                    fill="#333"
                    fontWeight={500}
                  >
                    {anno.label}
                  </text>
                </g>
              );

            case "arrow_up":
              return (
                <g key={`anno-${i}`} opacity={opacity}>
                  <circle cx={ax} cy={ay} r={5} fill="#e74c3c" />
                  <line
                    x1={ax}
                    y1={ay - 12}
                    x2={ax}
                    y2={ay - 40}
                    stroke="#e74c3c"
                    strokeWidth={2}
                  />
                  <polygon
                    points={`${ax},${ay - 12} ${ax - 5},${ay - 22} ${ax + 5},${ay - 22}`}
                    fill="#e74c3c"
                  />
                  <text
                    x={ax}
                    y={ay - 48}
                    textAnchor="middle"
                    fontSize={14}
                    fill="#333"
                    fontWeight={500}
                  >
                    {anno.label}
                  </text>
                </g>
              );

            case "arrow_down":
              return (
                <g key={`anno-${i}`} opacity={opacity}>
                  <circle cx={ax} cy={ay} r={5} fill="#e74c3c" />
                  <line
                    x1={ax}
                    y1={ay + 12}
                    x2={ax}
                    y2={ay + 40}
                    stroke="#e74c3c"
                    strokeWidth={2}
                  />
                  <polygon
                    points={`${ax},${ay + 12} ${ax - 5},${ay + 22} ${ax + 5},${ay + 22}`}
                    fill="#e74c3c"
                  />
                  <text
                    x={ax}
                    y={ay + 58}
                    textAnchor="middle"
                    fontSize={14}
                    fill="#333"
                    fontWeight={500}
                  >
                    {anno.label}
                  </text>
                </g>
              );

            case "vertical_line":
              return (
                <g key={`anno-${i}`} opacity={opacity}>
                  <line
                    x1={ax}
                    y1={PAD}
                    x2={ax}
                    y2={SVG_H - PAD}
                    stroke="#e74c3c"
                    strokeWidth={1.5}
                    strokeDasharray="6,4"
                  />
                  <text
                    x={ax}
                    y={PAD - 8}
                    textAnchor="middle"
                    fontSize={14}
                    fill="#333"
                    fontWeight={500}
                  >
                    {anno.label}
                  </text>
                </g>
              );

            default:
              return (
                <g key={`anno-${i}`} opacity={opacity}>
                  <circle cx={ax} cy={ay} r={6} fill="#e74c3c" />
                  <text
                    x={ax}
                    y={ay - 14}
                    textAnchor="middle"
                    fontSize={14}
                    fill="#333"
                    fontWeight={500}
                  >
                    {anno.label}
                  </text>
                </g>
              );
          }
        })}
      </svg>
    </div>
  );
};
