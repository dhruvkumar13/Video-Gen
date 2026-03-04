import React from "react";
import katex from "katex";

interface KaTeXProps {
  latex: string;
  fontSize?: number;
  color?: string;
  colorMap?: Record<string, string>;
}

/**
 * Renders a LaTeX string to HTML using KaTeX.
 *
 * colorMap applies inline color overrides — keys are TeX substrings,
 * values are CSS colors (e.g. {"x": "#e74c3c"}).
 */
export const KaTeX: React.FC<KaTeXProps> = ({
  latex,
  fontSize = 28,
  color = "#000000",
  colorMap,
}) => {
  // If colorMap provided, wrap matching substrings in \textcolor
  let processedLatex = latex;
  if (colorMap) {
    for (const [term, clr] of Object.entries(colorMap)) {
      // Escape special regex chars in the TeX string
      const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      processedLatex = processedLatex.replace(
        new RegExp(escaped, "g"),
        `\\textcolor{${clr}}{${term}}`
      );
    }
  }

  let html = "";
  try {
    html = katex.renderToString(processedLatex, {
      throwOnError: false,
      displayMode: true,
    });
  } catch {
    html = `<span style="color:red">LaTeX error</span>`;
  }

  return (
    <div
      style={{ fontSize, color, lineHeight: 1.4 }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
};
