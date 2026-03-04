---
name: math-tutor-video
description: >
  Generate animated math tutoring videos with step-by-step solutions.
  Triggers on requests for math explanations, calculus tutorials,
  derivative/integral visualizations, or educational math content.
---

# Math Tutor Video Generator

An AI-powered skill that turns math questions into animated tutorial videos
with voice narration. Supports Calculus 1 topics including derivatives,
integrals, limits, and graphing.

## Default Workflow

```
Student describes problem (chat)
  → GPT-5.3 clarifies the question
  → AI Solver generates step-by-step JSON
  → Renderer (Manim or Remotion) produces animated video
  → ElevenLabs TTS generates narration audio
  → ffmpeg merges video + audio
  → Student watches the result
```

## Setup

### Prerequisites

- Python 3.10+
- Node.js 18+ (for Remotion renderer)
- ffmpeg (`brew install ffmpeg`)
- LaTeX (`brew install texlive`)

### Installation

```bash
# Python dependencies
pip install -r requirements.txt

# Remotion dependencies (for React renderer)
cd remotion && npm install && cd ..
```

### Environment Variables

Create a `.env` file:

```env
OPENAI_API_KEY=sk-...         # Required — GPT-5.3 for AI solving + chat
ELEVEN_API_KEY=sk_...          # Optional — ElevenLabs voice narration
MEM0_API_KEY=m0-...            # Optional — Student preference memory
```

### Run

```bash
python3 server.py
# Open http://localhost:4000
```

## Architecture

### Pipeline Flow

| Stage | Module | Description |
|-------|--------|-------------|
| Chat | `server.py` | Conversational UI to clarify the question |
| Solve | `ai_solver.py` | GPT-5.3 generates structured step-by-step JSON |
| Render | `generate.py` / `render_remotion.py` | Manim or Remotion produces MP4 |
| Narrate | `tts.py` | ElevenLabs synthesizes narration audio |
| Merge | `merge_audio.py` | ffmpeg combines video + audio |
| Memory | `memory.py` | mem0 stores student preferences across sessions |

### Dual Renderer

Both renderers consume the same `question.json` schema:

- **Manim** (default) — Python-based, LaTeX-native, battle-tested animations
- **Remotion** — React-based, KaTeX rendering, faster iteration on UI

Toggle in the web UI header, or pass `"renderer": "remotion"` in API calls.

## Animation Types

The AI solver generates a sequence of steps. Each step has a `type`:

| Type | Description | Key Fields |
|------|-------------|------------|
| `write` | Writes new LaTeX on the board | `latex`, `narration` |
| `transform` | Morphs the last equation into a new one | `latex_to`, `narration` |
| `highlight` | Writes LaTeX then highlights specific terms | `latex`, `highlight_terms`, `narration` |
| `color_transform` | Transforms with color-coded terms | `latex_to`, `colors`, `narration` |
| `graph` | Plots a function on axes | `function`, `x_range`, `y_range`, `narration` |
| `tangent` | Shows function with tangent line at a point | `function`, `x_range`, `y_range`, `x_point`, `narration` |
| `area` | Shades area under a curve | `function`, `x_range`, `y_range`, `area_range`, `narration` |
| `step_label` | Section header (clears the board) | `label`, `narration` |

### Whiteboard Behavior

- `write` and `highlight` steps **accumulate** on the board (equations stack vertically)
- `transform` and `color_transform` steps **replace** the last equation in-place
- `step_label`, `graph`, `tangent`, and `area` steps **wipe** the board first
- The board auto-scrolls when content exceeds available space

## Question JSON Schema

```json
{
  "title": "Derivative of a Polynomial",
  "problem_latex": "\\frac{d}{dx}(x^4 - 3x^2 + 5)",
  "steps": [
    {
      "type": "step_label",
      "label": "Step 1: Apply the Power Rule",
      "narration": "Let's start by applying the power rule to each term."
    },
    {
      "type": "write",
      "latex": "\\frac{d}{dx}(x^4) = 4x^3",
      "narration": "The derivative of x to the fourth is four x cubed."
    },
    {
      "type": "transform",
      "latex_to": "f'(x) = 4x^3 - 6x",
      "narration": "Combining all terms, we get the final derivative."
    },
    {
      "type": "graph",
      "function": "4*x**3 - 6*x",
      "x_range": [-3, 3, 1],
      "y_range": [-10, 10, 2],
      "narration": "Here's the graph of the derivative function."
    }
  ]
}
```

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat/new` | POST | Start a new chat session |
| `/api/chat/<id>` | POST | Send a message `{"message": "..."}` |
| `/api/chat/<id>` | GET | Poll chat history |
| `/api/chat/<id>/generate` | POST | Trigger video generation `{"renderer": "manim"}` |
| `/api/generate` | POST | Direct generation `{"question": "...", "renderer": "manim"}` |
| `/api/status/<id>` | GET | Poll generation progress |
| `/api/video/<id>` | GET | Download the rendered MP4 |
| `/api/preferences` | GET/POST/DELETE | Manage student preferences |

## File Structure

```
Video Gen/
├── server.py              # Flask app + chatbot UI + API endpoints
├── ai_solver.py           # GPT-5.3 solution generator
├── generate.py            # Manim render pipeline
├── render_remotion.py     # Remotion render wrapper
├── scene.py               # Manim scene class
├── animations.py          # 8 Manim animation handlers
├── tts.py                 # ElevenLabs TTS
├── merge_audio.py         # ffmpeg audio-video merge
├── memory.py              # mem0 preference storage
├── questions.json         # Sample question bank
├── requirements.txt       # Python dependencies
├── .env                   # API keys
├── SKILL.md               # This file
├── CLAUDE.md              # Claude Code project instructions
├── remotion/              # Remotion React project
│   ├── package.json
│   ├── tsconfig.json
│   ├── remotion.config.ts
│   └── src/
│       ├── index.ts
│       ├── Root.tsx
│       ├── MathScene.tsx
│       └── components/
│           ├── KaTeX.tsx
│           └── Graph.tsx
└── jobs/                  # Runtime job directories
    └── {uuid}/
        ├── chat.json
        ├── question.json
        ├── status.json
        ├── narration.mp3
        ├── final.mp4
        └── media/videos/...
```

## Common Scripts

```bash
# Start the server
python3 server.py

# Generate from CLI (Manim)
python3 generate.py <question_id>

# Open Remotion Studio (visual editor)
cd remotion && npx remotion studio

# Render with Remotion directly
cd remotion && npx remotion render src/index.ts MathScene out.mp4 --props=../jobs/<uuid>/question.json
```

## Student Preferences

Preferences persist via mem0 cloud memory and shape how the AI solver generates solutions:

| Preference | Effect |
|------------|--------|
| More Graphs | Includes more visual plots |
| More Detail | Breaks solutions into smaller steps |
| Simpler Language | Uses simpler explanations |
| Color-Coded | Highlights equation parts with colors |
| More Examples | Adds additional examples and analogies |
| Concise | Keeps explanations brief |
