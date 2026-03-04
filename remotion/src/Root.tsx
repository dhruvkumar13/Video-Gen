import React from "react";
import { Composition } from "remotion";
import { MathScene, calculateDuration } from "./MathScene";
import type { QuestionData } from "./MathScene";

const FPS = 30;
const WIDTH = 1280;
const HEIGHT = 720;

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="MathScene"
      component={MathScene as unknown as React.FC<Record<string, unknown>>}
      durationInFrames={300}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
      defaultProps={
        {
          title: "Math Tutorial",
          problem_latex: "x^2",
          steps: [],
        } as Record<string, unknown>
      }
      calculateMetadata={async ({ props }) => ({
        durationInFrames: calculateDuration(props as unknown as QuestionData),
      })}
    />
  );
};
