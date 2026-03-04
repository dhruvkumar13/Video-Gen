"""
Render a math tutorial video using Remotion (React-based renderer).

This is the counterpart to generate.py's render_job() for the Manim pipeline.
Both read the same question.json but produce video through different engines.
"""

import subprocess
import os
import logging

logger = logging.getLogger(__name__)

# Path to the remotion project directory (relative to repo root)
REMOTION_DIR = os.path.join(os.path.dirname(__file__), "remotion")


_bundle_path = None


def _ensure_bundle():
    """Build the Remotion bundle once and reuse for subsequent renders."""
    global _bundle_path
    if _bundle_path and os.path.isdir(_bundle_path):
        return _bundle_path

    bundle_dir = os.path.join(REMOTION_DIR, "bundle")
    index_file = os.path.join(bundle_dir, "index.html")

    if os.path.isfile(index_file):
        _bundle_path = bundle_dir
        logger.info("Using existing Remotion bundle: %s", bundle_dir)
        return _bundle_path

    logger.info("Building Remotion bundle (one-time)...")
    cmd = ["npx", "remotion", "bundle", "src/index.ts", f"--out-dir={bundle_dir}"]
    result = subprocess.run(cmd, cwd=REMOTION_DIR, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        logger.warning("Bundle failed, falling back to direct render: %s",
                       result.stderr[-300:] if result.stderr else "")
        return None

    _bundle_path = bundle_dir
    logger.info("Remotion bundle ready: %s", bundle_dir)
    return _bundle_path


def invalidate_bundle():
    """Delete the cached bundle so it's rebuilt on next render."""
    global _bundle_path
    bundle_dir = os.path.join(REMOTION_DIR, "bundle")
    if os.path.isdir(bundle_dir):
        import shutil
        shutil.rmtree(bundle_dir)
        logger.info("Remotion bundle invalidated")
    _bundle_path = None


def render_with_remotion(job_dir: str) -> str:
    """Render a video using Remotion from a job directory's question.json.

    Args:
        job_dir: Absolute path to the job directory containing question.json

    Returns:
        Path to the rendered MP4 file.

    Raises:
        RuntimeError: If the render fails.
    """
    question_file = os.path.join(job_dir, "question.json")
    if not os.path.isfile(question_file):
        raise FileNotFoundError(f"question.json not found in {job_dir}")

    # Output path — matches Manim convention for easy swapping
    output_path = os.path.join(job_dir, "media", "videos", "scene", "720p30", "TutorialScene.mp4")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    bundle = _ensure_bundle()
    if bundle:
        cmd = [
            "npx", "remotion", "render",
            bundle,
            "MathScene",
            output_path,
            f"--props={question_file}",
            "--concurrency=1",
        ]
    else:
        cmd = [
            "npx", "remotion", "render",
            "src/index.ts",
            "MathScene",
            output_path,
            f"--props={question_file}",
            "--concurrency=1",
        ]

    logger.info("Remotion render: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            cwd=REMOTION_DIR,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            stderr_tail = result.stderr[-800:] if result.stderr else ""
            logger.error("Remotion render failed (exit %d):\n%s", result.returncode, stderr_tail)
            raise RuntimeError(f"Remotion render failed: {stderr_tail}")

        if not os.path.isfile(output_path):
            raise RuntimeError("Remotion produced no output file")

        size = os.path.getsize(output_path)
        if size == 0:
            os.remove(output_path)
            raise RuntimeError("Remotion produced empty video file")

        logger.info("Remotion render complete: %s (%d bytes)", output_path, size)
        return output_path

    except subprocess.TimeoutExpired:
        raise RuntimeError("Remotion render timed out (300s)")
