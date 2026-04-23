---
name: tts
description: >
  Local text-to-speech synthesis using Piper TTS. Use this skill when the user
  asks to "read this aloud", "speak this", "convert to speech", "generate audio",
  "TTS", "text to speech", "read it to me", "say this out loud", or wants any
  text converted into spoken audio. Also use when the user asks about available
  voices or wants to change TTS settings.
version: 0.1.0
---

# Piper TTS

Synthesize text to natural-sounding speech using the local Piper TTS engine.

## Available Tools

Use the MCP tools from the `piper-tts` server:

- **piper_tts_synthesize** — Convert text to speech audio (MP3 or WAV)
- **piper_tts_list_voices** — Show available voice models
- **piper_tts_health** — Check that Piper is properly configured

## Workflow

1. If unsure about setup, call `piper_tts_health` first to verify Piper is ready.
2. Call `piper_tts_synthesize` with the text to speak.
3. The tool returns a file path. Use the `playback_hint` field to play it, or inform the user where the file was saved.

## Tips

- For long text, the server automatically chunks at sentence boundaries (~500 chars) to prevent timeouts.
- Default speed is 0.8333 (slightly faster than normal). Increase toward 1.0 for slower, more deliberate speech. Decrease toward 0.5 for fast narration.
- If ffmpeg is installed, output is MP3. Otherwise falls back to WAV.
- To play audio on macOS, run the command in `playback_hint` via Bash.
