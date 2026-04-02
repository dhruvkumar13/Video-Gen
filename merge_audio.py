"""
Merge narration audio with rendered video using ffmpeg.

Features:
- Handles mismatched durations (loops video or pads audio)
- Generates soft ambient background music (synthesized, no external files)
- Mixes narration + music at the right volume balance
"""

import subprocess
import os
import logging

logger = logging.getLogger(__name__)

import shutil
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"

# Background music volume relative to narration (0.0 = silent, 1.0 = same volume)
BG_MUSIC_VOLUME = 0.12


def _get_duration(file_path):
    """Get the duration of a media file in seconds using ffprobe.

    Args:
        file_path: Path to audio or video file

    Returns:
        Duration in seconds (float), or None if detection fails
    """
    cmd = [
        FFPROBE,
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception as e:
        logger.warning("Could not get duration of %s: %s", file_path, e)
    return None


def _generate_bg_music(duration, output_path):
    """Generate a soft ambient background music track using ffmpeg synthesis.

    Creates a warm C-major chord pad (C3 + E3 + G3 + C4) with a gentle
    fade-in and fade-out. Sounds like a soft synth pad — unobtrusive under
    voice narration.

    Args:
        duration: Length in seconds
        output_path: Path to save the generated MP3

    Returns:
        output_path if successful, None if generation fails
    """
    # Frequencies for a warm C-major chord (Hz)
    # C3=130.81, E3=164.81, G3=196.00, C4=261.63
    # Each sine wave at low amplitude, summed together
    pad_expr = (
        "0.25*sin(2*PI*130.81*t)"
        "+0.20*sin(2*PI*164.81*t)"
        "+0.20*sin(2*PI*196.00*t)"
        "+0.15*sin(2*PI*261.63*t)"
        "+0.08*sin(2*PI*329.63*t)"   # E4 — adds shimmer
    )

    # Fade in over 3s, fade out over 4s
    fade_in = 3.0
    fade_out = 4.0

    cmd = [
        FFMPEG,
        "-y",
        "-f", "lavfi",
        "-i", f"aevalsrc={pad_expr}:s=44100:d={duration}",
        "-af", f"afade=t=in:d={fade_in},afade=t=out:st={max(0, duration - fade_out)}:d={fade_out}",
        "-c:a", "libmp3lame",
        "-b:a", "128k",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            logger.warning("Background music generation failed: %s",
                           result.stderr[-300:] if result.stderr else "")
            return None

        if os.path.isfile(output_path) and os.path.getsize(output_path) > 100:
            logger.info("Generated background music: %s (%.1fs)", output_path, duration)
            return output_path
        return None

    except Exception as e:
        logger.warning("Background music generation error: %s", e)
        return None


def merge_video_audio(video_path, audio_path, output_path):
    """Merge video and audio using ffmpeg.

    Handles duration mismatches gracefully:
    - If audio is longer, the video last frame is held to match.
    - If video is longer, audio is padded with silence.

    Args:
        video_path: Path to the input video (MP4 from Manim)
        audio_path: Path to the narration audio (MP3)
        output_path: Path for the output merged video (MP4)

    Returns:
        output_path if successful, None if merging fails.
    """
    if not os.path.isfile(video_path):
        logger.error("Video file not found: %s", video_path)
        return None
    if not os.path.isfile(audio_path):
        logger.error("Audio file not found: %s", audio_path)
        return None

    video_duration = _get_duration(video_path)
    audio_duration = _get_duration(audio_path)
    logger.info("Video duration: %.2fs, Audio duration: %.2fs",
                video_duration or 0, audio_duration or 0)

    # Generate background music matching the longer of video/audio duration
    target_duration = max(video_duration or 0, audio_duration or 0)
    bg_music_path = None
    if target_duration > 0:
        bg_music_path = os.path.join(os.path.dirname(output_path), "bg_music.mp3")
        bg_music_path = _generate_bg_music(target_duration + 2, bg_music_path)

    # Build ffmpeg command
    # Strategy: use -shortest if video is longer, otherwise extend video
    # with a loop to match audio length.
    # If background music is available, mix it under narration using amix filter.

    if bg_music_path:
        # 3-input merge: video + narration + background music
        # amix combines narration (full vol) + music (BG_MUSIC_VOLUME)
        weight_str = f"1 {BG_MUSIC_VOLUME}"

        if video_duration and audio_duration and audio_duration > video_duration:
            cmd = [
                FFMPEG,
                "-y",
                "-stream_loop", "-1",
                "-i", video_path,
                "-i", audio_path,
                "-i", bg_music_path,
                "-filter_complex",
                f"[1:a][2:a]amix=inputs=2:duration=first:weights={weight_str}[aout]",
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                output_path,
            ]
        else:
            cmd = [
                FFMPEG,
                "-y",
                "-i", video_path,
                "-i", audio_path,
                "-i", bg_music_path,
                "-filter_complex",
                f"[1:a][2:a]amix=inputs=2:duration=first:weights={weight_str}[aout]",
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                output_path,
            ]
    else:
        # Fallback: no background music — just narration
        if video_duration and audio_duration and audio_duration > video_duration:
            cmd = [
                FFMPEG,
                "-y",
                "-stream_loop", "-1",
                "-i", video_path,
                "-i", audio_path,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                output_path,
            ]
        else:
            cmd = [
                FFMPEG,
                "-y",
                "-i", video_path,
                "-i", audio_path,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                output_path,
            ]

    logger.info("Merging video + audio + music: %s", " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error("ffmpeg merge failed (exit %d): %s",
                         result.returncode, result.stderr[-500:] if result.stderr else "")
            return None

        if not os.path.isfile(output_path):
            logger.error("Expected output file not created: %s", output_path)
            return None

        output_size = os.path.getsize(output_path)
        if output_size == 0:
            logger.error("Merged output is 0 bytes — ffmpeg produced empty file")
            os.remove(output_path)
            return None

        logger.info("Merged video saved: %s (%d bytes)", output_path, output_size)
        return output_path

    except subprocess.TimeoutExpired:
        logger.error("ffmpeg merge timed out (300s limit)")
        return None
    except Exception as e:
        logger.error("ffmpeg merge error: %s", e)
        return None
    finally:
        # Clean up temporary background music file
        if bg_music_path and os.path.isfile(bg_music_path):
            try:
                os.remove(bg_music_path)
            except Exception:
                pass
