# Piper TTS Plugin

Local text-to-speech synthesis for Claude, powered by [Piper](https://github.com/rhasspy/piper).

## What it does

Converts text into natural-sounding speech audio using Piper TTS, a fast local speech synthesis engine. No cloud APIs, no network calls — everything runs on your machine.

## Components

| Component | Name | Purpose |
|-----------|------|---------|
| MCP Server | piper-tts | Speech synthesis via three tools |
| Skill | tts | Triggers on voice/speech requests |

### Tools

- **piper_tts_synthesize** — Convert text to MP3/WAV audio
- **piper_tts_list_voices** — List installed voice models
- **piper_tts_health** — Verify Piper setup

## Prerequisites

1. **Piper TTS** binary installed ([releases](https://github.com/rhasspy/piper/releases))
2. At least one **.onnx voice model** ([voice samples](https://rhasspy.github.io/piper-samples/))
3. **ffmpeg** (optional, for MP3 output — falls back to WAV)
4. **Python 3.10+** with `mcp` and `pydantic` packages

## Setup

Set these environment variables before installing the plugin:

| Variable | Required | Description |
|----------|----------|-------------|
| `PIPER_BIN` | Yes | Path to the Piper binary (e.g., `/usr/local/bin/piper`) |
| `PIPER_MODEL_DIR` | Yes | Directory containing `.onnx` voice model files |
| `PIPER_OUTPUT_DIR` | No | Where to save audio files (default: system temp dir) |

Install Python dependencies:

```bash
pip install mcp pydantic
```

## Usage

Ask Claude to read something aloud:

- "Read this summary to me"
- "Convert this to speech"
- "What voices are available?"
- "Say this out loud in a slower speed"

## License

MIT
