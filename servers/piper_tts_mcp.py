#!/usr/bin/env python3
"""
Piper TTS MCP Server

A FastMCP server that wraps Piper TTS for local speech synthesis.
Accepts text, synthesizes via Piper, converts to MP3 via ffmpeg,
and returns the audio file path for playback.

Requires:
  - Piper TTS binary (https://github.com/rhasspy/piper)
  - At least one .onnx voice model
  - ffmpeg (optional, for MP3 output — falls back to WAV)
"""

import base64
import io
import json
import os
import re
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict, field_validator

# ── Defaults (overridable via env vars) ──────────────────────────
PIPER_BIN = os.environ.get("PIPER_BIN", "piper")
MODEL_DIR = os.environ.get("PIPER_MODEL_DIR", "")
OUTPUT_DIR = os.environ.get("PIPER_OUTPUT_DIR", tempfile.gettempdir())
MAX_CHUNK_CHARS = 500

# ── Server ───────────────────────────────────────────────────────
mcp = FastMCP("piper_tts_mcp")


# ── Utility functions ────────────────────────────────────────────

def _find_model_dir() -> str:
    """Resolve model directory from env or common locations."""
    if MODEL_DIR and os.path.isdir(MODEL_DIR):
        return MODEL_DIR
    # Common locations
    candidates = [
        Path.home() / "projects" / "zeropoint" / "models" / "piper",
        Path.home() / ".local" / "share" / "piper" / "models",
        Path.home() / "piper-models",
        Path("/usr/share/piper/models"),
    ]
    for c in candidates:
        if c.is_dir() and any(c.glob("*.onnx")):
            return str(c)
    return ""


def _find_piper() -> str:
    """Resolve Piper binary path."""
    if os.path.isfile(PIPER_BIN):
        return PIPER_BIN
    # Check PATH
    import shutil
    found = shutil.which("piper")
    if found:
        return found
    # Common locations
    candidates = [
        Path.home() / "anaconda3" / "bin" / "piper",
        Path.home() / ".local" / "bin" / "piper",
        Path("/usr/local/bin/piper"),
        Path("/usr/bin/piper"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return PIPER_BIN  # return default, let error surface later


def _list_voices(model_dir: str) -> list[str]:
    """List available .onnx voice models."""
    if not model_dir or not os.path.isdir(model_dir):
        return []
    return sorted(p.stem for p in Path(model_dir).glob("*.onnx"))


def _split_text(text: str) -> list[str]:
    """Split text into sentence-bounded chunks under MAX_CHUNK_CHARS."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""

    for sent in sentences:
        if current and len(current) + len(sent) + 1 > MAX_CHUNK_CHARS:
            chunks.append(current.strip())
            current = sent
        else:
            current = f"{current} {sent}" if current else sent

    if current.strip():
        chunks.append(current.strip())

    # Hard-split any remaining oversized chunks on whitespace
    final: list[str] = []
    for chunk in chunks:
        if len(chunk) <= MAX_CHUNK_CHARS:
            final.append(chunk)
        else:
            words = chunk.split()
            sub = ""
            for w in words:
                if sub and len(sub) + len(w) + 1 > MAX_CHUNK_CHARS:
                    final.append(sub)
                    sub = w
                else:
                    sub = f"{sub} {w}" if sub else w
            if sub:
                final.append(sub)

    return final


def _concat_wavs(paths: list[str]) -> bytes:
    """Concatenate multiple WAV files into one."""
    if len(paths) == 1:
        with open(paths[0], "rb") as f:
            return f.read()

    params = None
    frames: list[bytes] = []

    for p in paths:
        with wave.open(p, "rb") as wf:
            if params is None:
                params = wf.getparams()
            frames.append(wf.readframes(wf.getnframes()))

    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setparams(params)
        for f in frames:
            out.writeframes(f)

    return buf.getvalue()


def _wav_to_mp3(wav_bytes: bytes, bitrate: str = "192k") -> bytes:
    """Convert WAV to MP3 via ffmpeg. Returns empty bytes if unavailable."""
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", "pipe:0",
                "-codec:a", "libmp3lame",
                "-b:a", bitrate,
                "-f", "mp3",
                "pipe:1",
            ],
            input=wav_bytes,
            capture_output=True,
            timeout=60,
        )
        if result.returncode == 0 and len(result.stdout) > 0:
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return b""


def _synthesize(
    text: str,
    piper_bin: str,
    model_path: str,
    length_scale: str = "0.8333",
    noise_scale: str = "0.667",
    noise_w: str = "0.800",
    sentence_silence: str = "0.30",
) -> tuple[bytes, str]:
    """Run Piper TTS on text, return (audio_bytes, content_type).

    Chunks large text, concatenates WAV output, converts to MP3 if
    ffmpeg is available.
    """
    chunks = _split_text(text)
    tmp_paths: list[str] = []

    try:
        for i, chunk in enumerate(chunks):
            fd, tmp_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            tmp_paths.append(tmp_path)

            result = subprocess.run(
                [
                    piper_bin,
                    "--model", model_path,
                    "--output_file", tmp_path,
                    "--length_scale", length_scale,
                    "--noise_scale", noise_scale,
                    "--noise_w", noise_w,
                    "--sentence_silence", sentence_silence,
                ],
                input=chunk.encode("utf-8"),
                capture_output=True,
                timeout=120,
            )

            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(
                    f"Piper exit {result.returncode} on chunk "
                    f"{i + 1}/{len(chunks)}: {stderr}"
                )

        wav_audio = _concat_wavs(tmp_paths)
        mp3_audio = _wav_to_mp3(wav_audio)

        if mp3_audio:
            return mp3_audio, "audio/mpeg"
        return wav_audio, "audio/wav"

    finally:
        for p in tmp_paths:
            try:
                os.unlink(p)
            except OSError:
                pass


# ── Pydantic input models ────────────────────────────────────────

class SynthesizeInput(BaseModel):
    """Input for speech synthesis."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    text: str = Field(
        ...,
        description="Text to synthesize into speech. Supports up to ~10,000 characters.",
        min_length=1,
        max_length=10000,
    )
    voice: Optional[str] = Field(
        default=None,
        description=(
            "Voice model name (without .onnx extension). "
            "Use piper_tts_list_voices to see available voices. "
            "If omitted, uses the first available voice."
        ),
    )
    speed: Optional[float] = Field(
        default=0.8333,
        description="Speech speed (length_scale). Lower = faster. Default 0.8333 is ~120% speed.",
        ge=0.3,
        le=3.0,
    )
    output_format: Optional[str] = Field(
        default="file",
        description=(
            "How to return the audio. "
            "'file' saves to disk and returns the path (best for playback). "
            "'base64' returns base64-encoded audio inline."
        ),
    )

    @field_validator("voice")
    @classmethod
    def strip_onnx(cls, v: Optional[str]) -> Optional[str]:
        if v and v.endswith(".onnx"):
            return v[:-5]
        return v


# ── Tool definitions ─────────────────────────────────────────────

@mcp.tool(
    name="piper_tts_synthesize",
    annotations={
        "title": "Synthesize Speech",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def piper_tts_synthesize(params: SynthesizeInput) -> str:
    """Synthesize text to speech using Piper TTS.

    Converts text into natural-sounding speech audio using a local Piper
    voice model. Supports long text (auto-chunked), multiple voices, and
    adjustable speed. Returns an MP3 file path or base64-encoded audio.

    Args:
        params (SynthesizeInput): Validated input containing:
            - text (str): The text to speak (1–10,000 chars)
            - voice (Optional[str]): Voice model name (default: first available)
            - speed (Optional[float]): Speech speed / length_scale (default: 0.8333)
            - output_format (Optional[str]): 'file' or 'base64'

    Returns:
        str: JSON with audio file path or base64 data, plus metadata.
    """
    piper_bin = _find_piper()
    model_dir = _find_model_dir()

    if not os.path.isfile(piper_bin):
        return json.dumps({
            "error": f"Piper binary not found at '{piper_bin}'. "
                     "Set PIPER_BIN environment variable to the correct path."
        })

    voices = _list_voices(model_dir)
    if not voices:
        return json.dumps({
            "error": f"No voice models found in '{model_dir}'. "
                     "Set PIPER_MODEL_DIR to a directory containing .onnx voice files."
        })

    # Resolve voice
    voice = params.voice
    if voice:
        if voice not in voices:
            return json.dumps({
                "error": f"Voice '{voice}' not found. Available: {voices}"
            })
    else:
        voice = voices[0]

    model_path = os.path.join(model_dir, f"{voice}.onnx")

    try:
        audio_bytes, content_type = _synthesize(
            text=params.text,
            piper_bin=piper_bin,
            model_path=model_path,
            length_scale=str(params.speed),
        )
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Synthesis timed out (120s per chunk)."})

    ext = "mp3" if content_type == "audio/mpeg" else "wav"
    word_count = len(params.text.split())

    if params.output_format == "base64":
        encoded = base64.b64encode(audio_bytes).decode("ascii")
        return json.dumps({
            "audio_base64": encoded,
            "content_type": content_type,
            "voice": voice,
            "words": word_count,
            "size_bytes": len(audio_bytes),
        })
    else:
        # Save to file
        out_dir = OUTPUT_DIR
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"piper-tts-output.{ext}")
        with open(out_path, "wb") as f:
            f.write(audio_bytes)

        return json.dumps({
            "file": out_path,
            "content_type": content_type,
            "voice": voice,
            "words": word_count,
            "size_bytes": len(audio_bytes),
            "playback_hint": f"afplay '{out_path}'" if ext == "wav" else f"afplay '{out_path}'",
        })


@mcp.tool(
    name="piper_tts_list_voices",
    annotations={
        "title": "List Available Voices",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def piper_tts_list_voices() -> str:
    """List all available Piper TTS voice models.

    Scans the configured model directory for .onnx voice files and
    returns their names. Use these names with piper_tts_synthesize.

    Returns:
        str: JSON with list of voice names and model directory path.
    """
    model_dir = _find_model_dir()
    voices = _list_voices(model_dir)
    piper_bin = _find_piper()

    return json.dumps({
        "voices": voices,
        "count": len(voices),
        "model_dir": model_dir,
        "piper_bin": piper_bin,
        "piper_found": os.path.isfile(piper_bin),
    }, indent=2)


@mcp.tool(
    name="piper_tts_health",
    annotations={
        "title": "Check TTS Health",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def piper_tts_health() -> str:
    """Check that Piper TTS is properly configured and ready.

    Verifies the Piper binary exists, the model directory is accessible,
    and ffmpeg is available for MP3 conversion.

    Returns:
        str: JSON health report with status of each component.
    """
    import shutil

    piper_bin = _find_piper()
    model_dir = _find_model_dir()
    voices = _list_voices(model_dir)
    ffmpeg_found = shutil.which("ffmpeg") is not None

    issues: list[str] = []
    if not os.path.isfile(piper_bin):
        issues.append(f"Piper binary not found: {piper_bin}")
    if not model_dir or not os.path.isdir(model_dir):
        issues.append("No model directory found. Set PIPER_MODEL_DIR.")
    elif not voices:
        issues.append(f"No .onnx voice models in {model_dir}")
    if not ffmpeg_found:
        issues.append("ffmpeg not found — output will be WAV instead of MP3")

    return json.dumps({
        "status": "ok" if not issues else "degraded" if ffmpeg_found else "issues",
        "piper_bin": piper_bin,
        "piper_found": os.path.isfile(piper_bin),
        "model_dir": model_dir,
        "voices": voices,
        "voice_count": len(voices),
        "ffmpeg_available": ffmpeg_found,
        "output_format": "mp3" if ffmpeg_found else "wav",
        "output_dir": OUTPUT_DIR,
        "issues": issues,
    }, indent=2)


if __name__ == "__main__":
    mcp.run()
