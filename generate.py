#!/Library/Frameworks/Python.framework/Versions/3.10/bin/python3
"""
Math Tutoring Video Generator

Usage:
    python3 generate.py <question_id>            # Generate video
    python3 generate.py <question_id> --preview  # Generate and auto-open
"""
import json
import os
import sys
import subprocess


def load_question(question_id):
    """Load and validate a question from the question bank."""
    with open("questions.json", "r") as f:
        bank = json.load(f)
    for q in bank["questions"]:
        if q["id"] == question_id:
            return q
    return None


def _get_tex_env():
    """Return environment dict with TeX/Homebrew paths configured."""
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    texmf = "/opt/homebrew/Cellar/texlive/20250308_2/share/texmf-dist"
    env["TEXMFCNF"] = texmf + "/web2c:"
    env["TEXMFDIST"] = texmf
    return env


def render_job(job_dir: str) -> str:
    """Render a video from a job directory's question.json.

    Args:
        job_dir: Absolute path to job directory containing question.json

    Returns:
        Path to the generated video file

    Raises:
        RuntimeError: If Manim rendering fails
    """
    question_file = os.path.join(job_dir, "question.json")
    if not os.path.isfile(question_file):
        raise RuntimeError(f"question.json not found in {job_dir}")

    env = _get_tex_env()
    env["QUESTION_FILE"] = question_file

    media_dir = os.path.join(job_dir, "media")
    cmd = [
        sys.executable, "-m", "manim", "render", "-qm",
        "--media_dir", media_dir,
        "scene.py", "TutorialScene",
    ]

    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        raise RuntimeError(
            f"Manim rendering failed (exit {result.returncode}):\n"
            f"{result.stderr}"
        )

    video_path = os.path.join(
        media_dir, "videos", "scene", "720p30", "TutorialScene.mp4"
    )
    if not os.path.isfile(video_path):
        raise RuntimeError(f"Expected video not found at {video_path}")

    return video_path


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 generate.py <question_id> [--preview]")
        print("\nAvailable questions:")
        with open("questions.json", "r") as f:
            bank = json.load(f)
        for q in bank["questions"]:
            print(f"  {q['id']:20s} {q['title']}")
        sys.exit(1)

    question_id = sys.argv[1]
    preview = "--preview" in sys.argv

    # Validate question exists
    question = load_question(question_id)
    if not question:
        print(f"Error: Question '{question_id}' not found in questions.json")
        sys.exit(1)

    print(f"Generating video: {question['title']}")
    print(f"Steps: {len(question['steps'])}")

    # Configure environment with TeX paths and question ID
    env = _get_tex_env()
    env["QUESTION_ID"] = question_id

    # Build manim render command
    cmd = [sys.executable, "-m", "manim", "render", "-qm"]
    if preview:
        cmd.append("-p")
    cmd += ["scene.py", "TutorialScene"]

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env)

    if result.returncode == 0:
        print("\nDone! Video saved to: media/videos/scene/720p30/TutorialScene.mp4")
    else:
        print("\nError: Manim rendering failed.")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
