import React from "react";
import { interpolate } from "remotion";

interface GraphProps {
  fn: string;
  xRange: number[];
  yRange: number[];
  frame: number;
  duration: number;
  mode: "graph" | "tangent" | "area";
  xPoint?: number;
  areaRange?: number[];
}

// Safe math evaluation
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

/**
 * Renders a function graph as SVG with optional tangent line or shaded area.
 * Animates using stroke-dasharray for the curve drawing effect.
 */
export const Graph: React.FC<GraphProps> = ({
  fn,
  xRange,
  yRange,
  frame,
  duration,
  mode,
  xPoint,
  areaRange,
}) => {
  const [xMin, xMax] = xRange;
  const [yMin, yMax] = yRange;

  // Map math coords to SVG coords
  const toSvgX = (x: number) =>
    PAD + ((x - xMin) / (xMax - xMin)) * (SVG_W - 2 * PAD);
  const toSvgY = (y: number) =>
    SVG_H - PAD - ((y - yMin) / (yMax - yMin)) * (SVG_H - 2 * PAD);

  // Axes animation (0→40 frames)
  const axesOpacity = interpolate(frame, [0, 30], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Curve animation (30→90 frames)
  const curveProgress = interpolate(frame, [30, 90], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Extra element animation (80→duration)
  const extraProgress = interpolate(frame, [80, 110], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Generate curve path
  const numPoints = 200;
  const points: string[] = [];
  for (let i = 0; i <= numPoints; i++) {
    const x = xMin + (i / numPoints) * (xMax - xMin);
    const y = safeEval(fn, x);
    const clampedY = Math.max(yMin, Math.min(yMax, y));
    const sx = toSvgX(x);
    const sy = toSvgY(clampedY);
    points.push(`${sx},${sy}`);
  }
  const pathD = "M " + points.join(" L ");

  // Estimate path length for stroke-dasharray animation
  const pathLen = 2000;

  // Axis tick marks
  const xTicks: number[] = [];
  for (let t = Math.ceil(xMin); t <= Math.floor(xMax); t++) {
    if (t !== 0) xTicks.push(t);
  }
  const yTicks: number[] = [];
  for (let t = Math.ceil(yMin); t <= Math.floor(yMax); t++) {
    if (t !== 0) yTicks.push(t);
  }

  // Tangent line computation
  let tangentPath = "";
  let dotCx = 0;
  let dotCy = 0;
  if (mode === "tangent" && xPoint !== undefined) {
    const h = 0.001;
    const y0 = safeEval(fn, xPoint);
    const slope =
      (safeEval(fn, xPoint + h) - safeEval(fn, xPoint - h)) / (2 * h);
    const dx = 1.5;
    const x1 = xPoint - dx;
    const y1 = y0 + slope * -dx;
    const x2 = xPoint + dx;
    const y2 = y0 + slope * dx;
    tangentPath = `M ${toSvgX(x1)},${toSvgY(y1)} L ${toSvgX(x2)},${toSvgY(y2)}`;
    dotCx = toSvgX(xPoint);
    dotCy = toSvgY(y0);
  }

  // Area path
  let areaPath = "";
  if (mode === "area") {
    const [aMin, aMax] = areaRange || [xMin, xMax];
    const areaPoints: string[] = [];
    areaPoints.push(`${toSvgX(aMin)},${toSvgY(0)}`);
    for (let i = 0; i <= 100; i++) {
      const x = aMin + (i / 100) * (aMax - aMin);
      const y = safeEval(fn, x);
      const clampedY = Math.max(yMin, Math.min(yMax, y));
      areaPoints.push(`${toSvgX(x)},${toSvgY(clampedY)}`);
    }
    areaPoints.push(`${toSvgX(aMax)},${toSvgY(0)}`);
    areaPath = "M " + areaPoints.join(" L ") + " Z";
  }

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
          {/* X-axis */}
          <line
            x1={PAD}
            y1={toSvgY(0)}
            x2={SVG_W - PAD}
            y2={toSvgY(0)}
            stroke="#333333"
            strokeWidth={1.5}
          />
          {/* Y-axis */}
          <line
            x1={toSvgX(0)}
            y1={PAD}
            x2={toSvgX(0)}
            y2={SVG_H - PAD}
            stroke="#333333"
            strokeWidth={1.5}
          />
          {/* X ticks */}
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
          {/* Y ticks */}
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

        {/* Area (under curve) */}
        {mode === "area" && areaPath && (
          <path
            d={areaPath}
            fill="rgba(66,135,245,0.25)"
            opacity={extraProgress}
          />
        )}

        {/* Curve */}
        <path
          d={pathD}
          fill="none"
          stroke="#4285f4"
          strokeWidth={2.5}
          strokeDasharray={pathLen}
          strokeDashoffset={pathLen * (1 - curveProgress)}
        />

        {/* Tangent line */}
        {mode === "tangent" && tangentPath && (
          <g opacity={extraProgress}>
            <path
              d={tangentPath}
              fill="none"
              stroke="#e74c3c"
              strokeWidth={2.5}
            />
            <circle cx={dotCx} cy={dotCy} r={5} fill="#e74c3c" />
          </g>
        )}
      </svg>
    </div>
  );
};
