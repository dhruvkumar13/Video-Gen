import React from "react";
import { interpolate } from "remotion";

interface PointData {
  value: number;
  label: string;
  style: string;
}

interface IntervalData {
  from: number;
  to: number;
  color: string;
}

interface NumberLineProps {
  range: number[];
  points: PointData[];
  intervals?: IntervalData[];
  title?: string;
  frame: number;
  duration: number;
}

const SVG_W = 900;
const SVG_H = 500;
const PAD = 60;
const CENTER_Y = SVG_H / 2;

export const NumberLine: React.FC<NumberLineProps> = ({
  range,
  points,
  intervals,
  title,
  frame,
  duration,
}) => {
  const [rMin, rMax] = range;

  const toSvgX = (v: number) =>
    PAD + ((v - rMin) / (rMax - rMin)) * (SVG_W - 2 * PAD);

  // Animation phases
  const lineLen = SVG_W - 2 * PAD;
  const lineProgress = interpolate(frame, [0, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const intervalOpacity = interpolate(frame, [30, 60], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const pointsOpacity = interpolate(frame, [60, 90], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Integer ticks
  const ticks: number[] = [];
  for (let t = Math.ceil(rMin); t <= Math.floor(rMax); t++) {
    ticks.push(t);
  }

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
            y={80}
            textAnchor="middle"
            fontSize={22}
            fill="#222"
            fontWeight={600}
            opacity={titleOpacity}
          >
            {title}
          </text>
        )}

        {/* Main horizontal line with stroke-dasharray animation */}
        <line
          x1={PAD}
          y1={CENTER_Y}
          x2={SVG_W - PAD}
          y2={CENTER_Y}
          stroke="#333"
          strokeWidth={2}
          strokeDasharray={lineLen}
          strokeDashoffset={lineLen * (1 - lineProgress)}
        />

        {/* Arrow tips */}
        <g opacity={lineProgress}>
          <polygon
            points={`${PAD - 8},${CENTER_Y} ${PAD + 4},${CENTER_Y - 5} ${PAD + 4},${CENTER_Y + 5}`}
            fill="#333"
          />
          <polygon
            points={`${SVG_W - PAD + 8},${CENTER_Y} ${SVG_W - PAD - 4},${CENTER_Y - 5} ${SVG_W - PAD - 4},${CENTER_Y + 5}`}
            fill="#333"
          />
        </g>

        {/* Tick marks */}
        <g opacity={lineProgress}>
          {ticks.map((t) => {
            const x = toSvgX(t);
            return (
              <g key={t}>
                <line
                  x1={x}
                  y1={CENTER_Y - 8}
                  x2={x}
                  y2={CENTER_Y + 8}
                  stroke="#333"
                  strokeWidth={1.5}
                />
                <text
                  x={x}
                  y={CENTER_Y + 28}
                  textAnchor="middle"
                  fontSize={14}
                  fill="#555"
                >
                  {t}
                </text>
              </g>
            );
          })}
        </g>

        {/* Intervals */}
        {intervals &&
          intervals.map((iv, i) => (
            <line
              key={`iv-${i}`}
              x1={toSvgX(iv.from)}
              y1={CENTER_Y + 15}
              x2={toSvgX(iv.to)}
              y2={CENTER_Y + 15}
              stroke={iv.color}
              strokeWidth={6}
              strokeLinecap="round"
              opacity={intervalOpacity}
            />
          ))}

        {/* Points */}
        <g opacity={pointsOpacity}>
          {points.map((pt, i) => {
            const x = toSvgX(pt.value);
            let pointEl: React.ReactNode = null;

            switch (pt.style) {
              case "closed":
                pointEl = <circle cx={x} cy={CENTER_Y} r={7} fill="#e74c3c" />;
                break;
              case "open":
                pointEl = (
                  <circle
                    cx={x}
                    cy={CENTER_Y}
                    r={7}
                    fill="#ffffff"
                    stroke="#e74c3c"
                    strokeWidth={2.5}
                  />
                );
                break;
              case "arrow_left":
                pointEl = (
                  <>
                    <circle cx={x} cy={CENTER_Y} r={5} fill="#e74c3c" />
                    <line
                      x1={x}
                      y1={CENTER_Y}
                      x2={PAD}
                      y2={CENTER_Y}
                      stroke="#e74c3c"
                      strokeWidth={3}
                    />
                    <polygon
                      points={`${PAD},${CENTER_Y} ${PAD + 10},${CENTER_Y - 6} ${PAD + 10},${CENTER_Y + 6}`}
                      fill="#e74c3c"
                    />
                  </>
                );
                break;
              case "arrow_right":
                pointEl = (
                  <>
                    <circle cx={x} cy={CENTER_Y} r={5} fill="#e74c3c" />
                    <line
                      x1={x}
                      y1={CENTER_Y}
                      x2={SVG_W - PAD}
                      y2={CENTER_Y}
                      stroke="#e74c3c"
                      strokeWidth={3}
                    />
                    <polygon
                      points={`${SVG_W - PAD},${CENTER_Y} ${SVG_W - PAD - 10},${CENTER_Y - 6} ${SVG_W - PAD - 10},${CENTER_Y + 6}`}
                      fill="#e74c3c"
                    />
                  </>
                );
                break;
              default:
                pointEl = <circle cx={x} cy={CENTER_Y} r={6} fill="#e74c3c" />;
            }

            return (
              <g key={`pt-${i}`}>
                {pointEl}
                <text
                  x={x}
                  y={CENTER_Y - 20}
                  textAnchor="middle"
                  fontSize={15}
                  fill="#333"
                  fontWeight={500}
                >
                  {pt.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
};
