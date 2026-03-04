# Math Tutoring Video Generator

## What This Does
A web-based math tutor that generates animated video lessons for Calculus 1 problems.
Students chat with an AI tutor to formulate their question, then the system generates
a step-by-step animated video with voice narration and background music. Videos accumulate
in a library for replay.

## Stack
- **Python 3.10** — use `python3` for all commands (at `/Library/Frameworks/Python.framework/Versions/3.10/bin/python3`)
- **Flask** — web server + API + inline HTML/CSS/JS frontend (all in `server.py`)
- **OpenAI GPT-5.3** — AI solution generation (`gpt-5.3-chat-latest` model) and chatbot
- **Manim Community Edition** — animated math visuals (original renderer)
- **Remotion v4.0.432** — React/TypeScript video renderer (newer, preferred)
- **ElevenLabs** — text-to-speech narration (Rachel voice, eleven_multilingual_v2 model)
- **mem0** — student preference memory (persists across sessions)
- **ffmpeg 8.0** — video/audio processing, background music synthesis
- **KaTeX** — LaTeX rendering in Remotion
- **Node.js v23.7.0** — for Remotion rendering

## Quick Start
```bash
pip install -r requirements.txt
cd remotion && npm install && cd ..
# Set keys in .env: OPENAI_API_KEY, ELEVEN_API_KEY, MEM0_API_KEY
python3 server.py
# Open http://localhost:4000
```

## Pipeline Flow (audio-first)
```
Student chats with AI tutor
  -> GPT determines question is ready ([READY] marker)
  -> Student clicks "Generate Video"
  -> POST /api/chat/{id}/generate
    1. AI solver (GPT-5.3) generates step-by-step JSON     [0-20%]
    2. ElevenLabs TTS generates per-step narration audio    [20-40%]
       -> Measures each audio segment duration via ffprobe
       -> Writes narration_duration into question.json
    3. Renderer (Manim or Remotion) produces video          [40-70%]
       -> Remotion reads narration_duration to match timing
    4. ffmpeg merges video + narration + background music   [70-90%]
    5. Complete — video plays in chat                       [100%]
```

**CRITICAL: Audio-first pipeline** — TTS runs BEFORE rendering. Each step's audio duration
is measured and written into `question.json` so the video renderer can match visual timing
to speech exactly. This prevents audio/video desync.

## Key Files

### Python Backend
| File | Purpose |
|------|---------|
| `server.py` | Flask app + ALL frontend HTML/CSS/JS (single-file UI) |
| `ai_solver.py` | GPT-5.3 solution generation with SYSTEM_PROMPT |
| `tts.py` | ElevenLabs TTS — per-step audio generation + duration measurement |
| `merge_audio.py` | ffmpeg merge: video + narration + synthesized background music |
| `render_remotion.py` | Remotion CLI wrapper (npx remotion render) |
| `generate.py` | CLI entry point + `render_job()` for Manim pipeline |
| `scene.py` | Manim scene class |
| `animations.py` | 8 Manim animation type handlers |
| `memory.py` | mem0 preference storage (single user_id "student") |
| `questions.json` | Sample question bank for CLI testing |

### Remotion Frontend (TypeScript)
| File | Purpose |
|------|---------|
| `remotion/src/MathScene.tsx` | Main composition — timeline, board state, all sub-views |
| `remotion/src/Root.tsx` | Remotion entry — uses `calculateMetadata` for dynamic duration |
| `remotion/src/index.ts` | Bundle entry point |
| `remotion/src/components/KaTeX.tsx` | LaTeX-to-HTML renderer with color mapping |
| `remotion/src/components/Graph.tsx` | SVG function plotter (graph/tangent/area) |

### Configuration
| File | Purpose |
|------|---------|
| `.env` | API keys: `OPENAI_API_KEY`, `ELEVEN_API_KEY`, `MEM0_API_KEY` |
| `.claude/launch.json` | Dev server preview config (port 4000) |
| `jobs/` | Per-job directories with question.json, status.json, audio, video |

## Animation Types & Whiteboard Model

The video works like a real whiteboard. Content ACCUMULATES on screen.

| Type | Behavior | Key Fields |
|------|----------|------------|
| `write` | Adds new line below (accumulates) | `latex` |
| `transform` | Replaces bottom line in-place | `latex_from`, `latex_to` |
| `highlight` | Adds line + flashes terms | `latex`, `highlight_terms` |
| `color_transform` | Replaces bottom line with colors | `latex_to`, `colors` |
| `step_label` | WIPES board for new section | `label` |
| `graph` | WIPES board for full-screen plot | `function`, `x_range`, `y_range` |
| `tangent` | WIPES board for tangent viz | `function`, `x_point`, ranges |
| `area` | WIPES board for shaded area | `function`, ranges, `area_range` |

**IMPORTANT**: The JSON uses `"animation"` as the key (NOT `"type"`). Every step also
requires a `"narration"` field for voice-over text.

**Whiteboard rules** — prefer `write` over `transform`. Students learn by seeing ALL
intermediate steps on screen simultaneously. Use `transform` ONLY for tiny simplifications.

## Teaching Philosophy (encoded in ai_solver.py SYSTEM_PROMPT)

The AI tutor is warm, patient, and explains things simply:
- **Big picture first** — explain WHAT and WHY before diving into algebra
- **Name techniques** — "This is the power rule — we bring the exponent down..."
- **Plain English narrations** — spoken like a real person, not a textbook
- **Intuition checks** — "Think of the derivative as the slope at that exact point"
- **Sanity checks** — "Let's double-check: the derivative of x^4 should give us 4x^3"
- **Visual arrows** — `\Rightarrow`, `\xrightarrow{\text{power rule}}`, `\underbrace`
- **Final answer on same page** — never wipe the board before the boxed answer
- **8-14 steps** — more steps = more learning, don't rush

## Voice & Audio

- **Voice**: Rachel (ElevenLabs) — warm, clear female voice
- **Model**: eleven_multilingual_v2 (high quality)
- **Settings**: stability=0.40, similarity_boost=0.75, style=0.30 (natural, less robotic)
- **Background music**: Auto-synthesized C-major chord pad (ffmpeg aevalsrc)
  - Mixed at 12% volume under narration
  - Fades in over 3s, fades out over 4s
  - Generated per-video to match exact duration

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/chat/new` | Create new chat session |
| POST | `/api/chat/<id>` | Send message, get AI reply |
| GET | `/api/chat/<id>` | Poll chat state |
| POST | `/api/chat/<id>/generate` | Trigger video generation |
| GET | `/api/status/<id>` | Poll generation progress |
| GET | `/api/video/<id>` | Stream finished video (prefers final.mp4 > raw) |
| GET | `/api/library` | List all completed videos (newest first) |
| GET | `/api/preferences` | Get stored preferences + available options |
| POST | `/api/preferences` | Save a preference (key or freetext) |
| DELETE | `/api/preferences` | Clear all preferences |

## Frontend (inline in server.py)

The entire UI is a single HTML page embedded in server.py's `HTML_PAGE` variable.
- **Light mode** — white/slate backgrounds, teal (#14b8a6) accent
- **Chatbot interface** — AI message bubbles, sample question chips, typing indicator
- **Renderer toggle** — switch between Manim and Remotion in the header
- **Preferences panel** — collapsible panel with toggle buttons (More Graphs, Simpler Language, etc.)
- **Video Library** — slide-in right panel showing all past videos, click to replay
- **Progress tracking** — inline progress bar during generation

## Known Constraints & Gotchas

### ffmpeg 8.0
- Does NOT support `-fflags +shortest` — use only `-shortest`
- The old flag produces 0-byte output files silently

### Remotion Rendering
- Video: 1280x720 at 30fps
- Duration is dynamic via `calculateMetadata` (reads from props)
- `narration_duration` in question.json drives per-step timing
- Fallback durations exist if TTS is unavailable
- Minimum durations prevent animations from being too short

### ElevenLabs TTS
- Falls back gracefully if API key missing or voice unavailable
- Pipeline continues without audio (video still renders)
- Audio segments are concatenated with ffmpeg concat demuxer

### Manim vs Remotion
- Both read the same `question.json` format
- Manim: Python-based, requires LaTeX installation, more mature animations
- Remotion: React/TypeScript, uses KaTeX (no LaTeX install needed), programmatic video
- Toggle in the header switches which renderer is used

## Job Directory Structure
```
jobs/{uuid}/
  chat.json          # Chat history + final_question
  question.json      # AI solution JSON (with narration_duration per step)
  status.json        # Pipeline status (status, step, progress, error)
  narration.mp3      # Combined narration audio
  final.mp4          # Merged video + narration + music (served to user)
  bg_music.mp3       # Temporary (cleaned up after merge)
  audio_segments/    # Per-step TTS clips (segment_000.mp3, ...)
  media/             # Manim output (if using Manim renderer)
    videos/scene/720p30/TutorialScene.mp4
```

## Environment Variables
- `OPENAI_API_KEY` — required for GPT-5.3 (chat + solution generation)
- `ELEVEN_API_KEY` — required for voice narration (optional — pipeline works without it)
- `MEM0_API_KEY` — required for preference memory (optional — works without it)

## TeX Configuration (macOS, Manim only)
The Manim renderer uses homebrew texlive. Environment variables set by generate.py:
- `TEXMFCNF` — points to texlive web2c config
- `TEXMFDIST` — points to texlive distribution files
- `PATH` — prepends `/opt/homebrew/bin`
