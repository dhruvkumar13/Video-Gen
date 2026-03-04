"""
ElevenLabs TTS integration for narration audio.

Generates voice narration for each step in a math solution,
then concatenates into a single audio track using ffmpeg.
"""

import os
import json
import subprocess
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

import shutil

load_dotenv()

logger = logging.getLogger(__name__)

# Paths to ffmpeg/ffprobe — auto-detect or fall back to Homebrew (macOS)
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

# Preferred voice and model (with fallbacks)
# Female voices that sound warm and natural for tutoring:
#   "Rachel" — calm, clear, warm
#   "Aria"   — friendly, conversational
#   "Sarah"  — soft, approachable
PREFERRED_VOICE_NAME = "Rachel"
PREFERRED_MODEL_ID = "eleven_multilingual_v2"
FALLBACK_MODEL_ID = "eleven_flash_v2_5"
AUDIO_FORMAT = "mp3_44100_128"

# Voice settings for natural, conversational speech (less robotic)
VOICE_SETTINGS = {
    "stability": 0.40,            # Lower = more expressive variation (default 0.5)
    "similarity_boost": 0.75,     # Stay close to the voice's natural sound
    "style": 0.30,                # Light emotional expressiveness
    "use_speaker_boost": True,    # Enhances clarity
}


def _get_client():
    """Create and return an ElevenLabs client."""
    from elevenlabs import ElevenLabs

    api_key = os.getenv("ELEVEN_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVEN_API_KEY not set in environment")
    return ElevenLabs(api_key=api_key)


def _pick_voice(client):
    """Pick the best available voice, preferring PREFERRED_VOICE_NAME.

    Returns:
        voice_id (str)
    """
    try:
        voices_response = client.voices.get_all()
        voices = voices_response.voices
    except Exception as e:
        logger.warning("Could not list voices: %s", e)
        # Return a known default voice ID (Rachel)
        return "21m00Tcm4TlvDq8ikWAM"

    if not voices:
        return "21m00Tcm4TlvDq8ikWAM"

    # Try to find the preferred voice by name
    for v in voices:
        if PREFERRED_VOICE_NAME.lower() in v.name.lower():
            logger.info("Using voice: %s (%s)", v.name, v.voice_id)
            return v.voice_id

    # Fall back to the first available voice
    logger.info("Preferred voice '%s' not found, using: %s (%s)",
                PREFERRED_VOICE_NAME, voices[0].name, voices[0].voice_id)
    return voices[0].voice_id


def _pick_model(client):
    """Pick the best available model, preferring PREFERRED_MODEL_ID.

    Returns:
        model_id (str)
    """
    try:
        models = client.models.list()
    except Exception as e:
        logger.warning("Could not list models: %s", e)
        return PREFERRED_MODEL_ID

    model_ids = [m.model_id for m in models]

    if PREFERRED_MODEL_ID in model_ids:
        return PREFERRED_MODEL_ID
    if FALLBACK_MODEL_ID in model_ids:
        logger.info("Preferred model not available, using fallback: %s",
                     FALLBACK_MODEL_ID)
        return FALLBACK_MODEL_ID

    # Use the first available model
    if model_ids:
        logger.info("Using first available model: %s", model_ids[0])
        return model_ids[0]

    return PREFERRED_MODEL_ID


def _get_audio_duration(file_path):
    """Get the duration of an audio file in seconds using ffprobe."""
    cmd = [
        FFPROBE,
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception as e:
        logger.warning("Could not get audio duration of %s: %s", file_path, e)
    return None


def _generate_segment(client, text, voice_id, model_id, output_path):
    """Generate a single audio segment for one narration text.

    Args:
        client: ElevenLabs client
        text: Narration text to convert to speech
        voice_id: ElevenLabs voice ID
        model_id: ElevenLabs model ID
        output_path: Path to save the MP3 file

    Returns:
        output_path if successful, None if failed
    """
    try:
        from elevenlabs import VoiceSettings

        audio = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=model_id,
            output_format=AUDIO_FORMAT,
            voice_settings=VoiceSettings(
                stability=VOICE_SETTINGS["stability"],
                similarity_boost=VOICE_SETTINGS["similarity_boost"],
                style=VOICE_SETTINGS["style"],
                use_speaker_boost=VOICE_SETTINGS["use_speaker_boost"],
            ),
        )

        with open(output_path, "wb") as f:
            for chunk in audio:
                f.write(chunk)

        file_size = os.path.getsize(output_path)
        if file_size < 100:
            logger.warning("Audio segment too small (%d bytes), may be empty: %s",
                           file_size, output_path)
            return None

        logger.info("Generated audio segment: %s (%d bytes)", output_path, file_size)
        return output_path

    except Exception as e:
        logger.warning("Failed to generate audio for text '%s...': %s",
                       text[:50], e)
        return None


def _concatenate_segments(segment_paths, output_path):
    """Concatenate multiple MP3 segments into one file using ffmpeg.

    Args:
        segment_paths: List of paths to MP3 segment files
        output_path: Path for the combined output MP3

    Returns:
        output_path if successful, None if failed
    """
    if not segment_paths:
        logger.warning("No audio segments to concatenate")
        return None

    if len(segment_paths) == 1:
        # Only one segment -- just copy it
        import shutil
        shutil.copy2(segment_paths[0], output_path)
        return output_path

    # Create a concat list file for ffmpeg
    list_dir = os.path.dirname(output_path)
    list_file = os.path.join(list_dir, "concat_list.txt")

    with open(list_file, "w") as f:
        for seg_path in segment_paths:
            # ffmpeg concat demuxer requires absolute paths or paths
            # relative to the list file. Use absolute for safety.
            abs_path = os.path.abspath(seg_path)
            f.write(f"file '{abs_path}'\n")

    cmd = [
        FFMPEG,
        "-y",                    # overwrite output
        "-f", "concat",          # concat demuxer
        "-safe", "0",            # allow absolute paths
        "-i", list_file,         # input list
        "-c", "copy",            # copy codec (no re-encoding)
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.warning("ffmpeg concat failed: %s", result.stderr)
            return None

        logger.info("Combined narration audio: %s (%d bytes)",
                    output_path, os.path.getsize(output_path))
        return output_path

    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg concat timed out")
        return None
    except Exception as e:
        logger.warning("ffmpeg concat error: %s", e)
        return None
    finally:
        # Clean up the list file
        if os.path.exists(list_file):
            os.remove(list_file)


def generate_narration(question_data, output_dir):
    """Generate combined narration audio for all steps.

    Also measures the duration of each audio segment and returns a mapping
    of step_index → duration_seconds so the video renderer can match timing.

    Args:
        question_data: The solution dict with steps containing 'narration' fields
        output_dir: Directory to save audio files

    Returns:
        Tuple of (audio_path, step_durations) where:
            audio_path: Path to the combined narration MP3, or None if TTS fails
            step_durations: Dict mapping step index → duration in seconds
                            (e.g. {0: 3.2, 1: 4.1, ...})
        The pipeline should continue without audio if audio_path is None.
    """
    try:
        client = _get_client()
    except Exception as e:
        logger.warning("Could not create ElevenLabs client: %s", e)
        return None, {}

    # Pick voice and model
    voice_id = _pick_voice(client)
    model_id = _pick_model(client)
    logger.info("TTS config: voice_id=%s, model_id=%s", voice_id, model_id)

    # Collect narration texts from all steps
    steps = question_data.get("steps", [])
    narrations = []
    for i, step in enumerate(steps):
        text = step.get("narration", "").strip()
        if text:
            narrations.append((i, text))

    if not narrations:
        logger.warning("No narration text found in solution steps")
        return None, {}

    # Create output directories
    segments_dir = os.path.join(output_dir, "audio_segments")
    os.makedirs(segments_dir, exist_ok=True)

    # Generate segments in parallel (max 4 concurrent to avoid rate limits)
    successful_segments = []  # list of (index, path) tuples
    step_durations = {}

    logger.info("Generating %d TTS segments in parallel (max_workers=2)...", len(narrations))

    def _gen_one(i, step_idx, text):
        """Generate one segment and return (i, step_idx, path, duration) or None."""
        segment_path = os.path.join(segments_dir, f"segment_{i:03d}.mp3")
        result = _generate_segment(client, text, voice_id, model_id, segment_path)
        if result:
            dur = _get_audio_duration(segment_path)
            return (i, step_idx, segment_path, dur)
        return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {}
        for i, (step_idx, text) in enumerate(narrations):
            future = executor.submit(_gen_one, i, step_idx, text)
            futures[future] = (i, step_idx)

        for future in as_completed(futures):
            i, step_idx = futures[future]
            try:
                result = future.result()
                if result:
                    idx, sidx, path, dur = result
                    successful_segments.append((idx, path))
                    if dur:
                        step_durations[sidx] = dur
                        logger.info("Step %d audio duration: %.2fs", sidx, dur)
            except Exception as e:
                logger.warning("TTS segment %d failed: %s", step_idx, e)

    if not successful_segments:
        logger.warning("All TTS segments failed, continuing without narration")
        return None, {}

    # Sort by original index for correct concatenation order
    successful_segments.sort(key=lambda x: x[0])

    logger.info("Generated %d/%d audio segments successfully",
                len(successful_segments), len(narrations))

    # Concatenate all segments into one file
    combined_path = os.path.join(output_dir, "narration.mp3")
    segment_paths = [path for _, path in successful_segments]
    result = _concatenate_segments(segment_paths, combined_path)

    if result:
        logger.info("Narration audio ready: %s", result)
    else:
        logger.warning("Failed to concatenate audio segments")

    return result, step_durations
