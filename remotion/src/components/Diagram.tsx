import React from "react";
import { interpolate } from "remotion";

interface ShapeData {
  type: string;
  position: number[] | number[][];
  label?: string;
  color?: string;
  size?: number;
}

interface DiagramProps {
  shapes: ShapeData[];
  title?: string;
  frame: number;
  duration: number;
}

const SVG_W = 900;
const SVG_H = 500;
const PAD = 60;

function computeBounds(shapes: ShapeData[]): {
  minX: number; maxX: number; minY: number; maxY: number;
} {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;

  for (const s of shapes) {
    const pos = s.position;
    if (pos.length === 0) continue;

    if (typeof pos[0] === "number") {
      const [x, y] = pos as number[];
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
    } else {
      for (const pt of pos as number[][]) {
        minX = Math.min(minX, pt[0]);
        maxX = Math.max(maxX, pt[0]);
        minY = Math.min(minY, pt[1]);
        maxY = Math.max(maxY, pt[1]);
      }
    }
  }

  if (!isFinite(minX)) {
    return { minX: -5, maxX: 5, minY: -5, maxY: 5 };
  }

  // Add some padding to bounds
  const dx = (maxX - minX) || 2;
  const dy = (maxY - minY) || 2;
  return {
    minX: minX - dx * 0.15,
    maxX: maxX + dx * 0.15,
    minY: minY - dy * 0.15,
    maxY: maxY + dy * 0.15,
  };
}

export const Diagram: React.FC<DiagramProps> = ({
  shapes,
  title,
  frame,
  duration,
}) => {
  const bounds = computeBounds(shapes);
  const { minX, maxX, minY, maxY } = bounds;

  const toSvgX = (x: number) =>
    PAD + ((x - minX) / (maxX - minX)) * (SVG_W - 2 * PAD);
  const toSvgY = (y: number) =>
    SVG_H - PAD - ((y - minY) / (maxY - minY)) * (SVG_H - 2 * PAD);

  const STAGGER = 15;

  const renderShape = (shape: ShapeData, idx: number) => {
    const color = shape.color || "#58a6ff";
    const size = shape.size || 1.0;
    const startFrame = idx * STAGGER;
    const opacity = interpolate(frame, [startFrame, startFrame + 20], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });

    const pos = shape.position;
    const isSinglePoint = typeof pos[0] === "number";
    const cx = isSinglePoint ? toSvgX((pos as number[])[0]) : 0;
    const cy = isSinglePoint ? toSvgY((pos as number[])[1]) : 0;

    let shapeEl: React.ReactNode = null;

    switch (shape.type) {
      case "circle": {
        const r = 30 * size;
        shapeEl = (
          <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth={2.5} />
        );
        break;
      }
      case "rectangle": {
        const w = 60 * size;
        const h = 40 * size;
        shapeEl = (
          <rect
            x={cx - w / 2}
            y={cy - h / 2}
            width={w}
            height={h}
            fill="none"
            stroke={color}
            strokeWidth={2.5}
          />
        );
        break;
      }
      case "triangle": {
        const s2 = 35 * size;
        const h = s2 * Math.sqrt(3) / 2;
        const pts = [
          `${cx},${cy - h * 2 / 3}`,
          `${cx - s2},${cy + h / 3}`,
          `${cx + s2},${cy + h / 3}`,
        ].join(" ");
        shapeEl = (
          <polygon points={pts} fill="none" stroke={color} strokeWidth={2.5} />
        );
        break;
      }
      case "line": {
        if (!isSinglePoint && (pos as number[][]).length >= 2) {
          const pts = pos as number[][];
          shapeEl = (
            <line
              x1={toSvgX(pts[0][0])}
              y1={toSvgY(pts[0][1])}
              x2={toSvgX(pts[1][0])}
              y2={toSvgY(pts[1][1])}
              stroke={color}
              strokeWidth={2.5}
            />
          );
        }
        break;
      }
      case "arrow": {
        const markerId = `arrowhead-${idx}`;
        if (!isSinglePoint && (pos as number[][]).length >= 2) {
          const pts = pos as number[][];
          shapeEl = (
            <>
              <defs>
                <marker
                  id={markerId}
                  markerWidth="10"
                  markerHeight="7"
                  refX="10"
                  refY="3.5"
                  orient="auto"
                >
                  <polygon points="0 0, 10 3.5, 0 7" fill={color} />
                </marker>
              </defs>
              <line
                x1={toSvgX(pts[0][0])}
                y1={toSvgY(pts[0][1])}
                x2={toSvgX(pts[1][0])}
                y2={toSvgY(pts[1][1])}
                stroke={color}
                strokeWidth={2.5}
                markerEnd={`url(#${markerId})`}
              />
            </>
          );
        }
        break;
      }
      case "point":
      default: {
        shapeEl = <circle cx={cx} cy={cy} r={5} fill={color} />;
        break;
      }
    }

    // Label position — offset above the center point
    const labelX = isSinglePoint
      ? cx
      : toSvgX(((pos as number[][])[0][0] + (pos as number[][])[1][0]) / 2);
    const labelY = isSinglePoint
      ? cy - 40 * size
      : toSvgY(
          Math.max((pos as number[][])[0][1], (pos as number[][])[1][1])
        ) - 20;

    return (
      <g key={idx} opacity={opacity}>
        {shapeEl}
        {shape.label && (
          <text
            x={labelX}
            y={labelY}
            textAnchor="middle"
            fontSize={16}
            fill="#333"
            fontWeight={500}
          >
            {shape.label}
          </text>
        )}
      </g>
    );
  };

  const titleOpacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateRight: "clamp",
  });

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
        {title && (
          <text
            x={SVG_W / 2}
            y={30}
            textAnchor="middle"
            fontSize={22}
            fill="#222"
            fontWeight={600}
            opacity={titleOpacity}
          >
            {title}
          </text>
        )}
        {shapes.map((s, i) => renderShape(s, i))}
      </svg>
    </div>
  );
};
