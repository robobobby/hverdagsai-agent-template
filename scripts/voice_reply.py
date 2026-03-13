#!/usr/bin/env python3
"""
voice_reply.py — Generate TTS audio via OpenAI API.

Usage:
  python3 scripts/voice_reply.py "Text to speak" [--output /path/to/file.mp3]
  python3 scripts/voice_reply.py --file briefing.txt [--voice onyx] [--speed 1.0]
  echo "Hello" | python3 scripts/voice_reply.py --stdin

Uses OpenAI tts-1 API. Cost: ~$0.015 per 1000 characters.
Voices: alloy, ash, ballad, coral, echo, fable, onyx, nova, sage, shimmer

Setup:
  1. pip3 install openai
  2. Add OpenAI API key to macOS Keychain:
     security add-generic-password -a "agent" -s "openai-api-key" -w "sk-..."
  3. Or set OPENAI_API_KEY environment variable
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def get_openai_key() -> str:
    """Get OpenAI API key from Keychain or environment."""
    # Try macOS Keychain first
    result = subprocess.run(
        ["security", "find-generic-password", "-s", "openai-api-key", "-w"],
        capture_output=True, text=True
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    # Try environment variable
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return key
    raise RuntimeError(
        "No OpenAI API key found.\n"
        "Add to Keychain: security add-generic-password -a \"agent\" -s \"openai-api-key\" -w \"sk-...\"\n"
        "Or set: export OPENAI_API_KEY=sk-..."
    )


def generate_tts(text: str, voice: str = "onyx", speed: float = 1.0,
                 output_path: str = None, model: str = "tts-1") -> str:
    """Generate TTS audio using OpenAI API. Returns path to MP3 file."""
    import openai
    client = openai.OpenAI(api_key=get_openai_key())

    if not output_path:
        output_path = tempfile.mktemp(suffix=".mp3", prefix="voice-")

    response = client.audio.speech.create(
        model=model,
        voice=voice,
        input=text,
        speed=speed,
        response_format="mp3",
    )

    with open(output_path, "wb") as f:
        for chunk in response.iter_bytes():
            f.write(chunk)

    size_kb = os.path.getsize(output_path) / 1024
    chars = len(text)
    cost_est = chars * 0.000015  # $0.015 per 1000 chars
    print(f"Generated: {output_path} ({size_kb:.0f}KB, {chars} chars, ~${cost_est:.4f})", file=sys.stderr)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate TTS audio via OpenAI")
    parser.add_argument("text", nargs="?", help="Text to speak")
    parser.add_argument("--file", "-f", help="Read text from file")
    parser.add_argument("--stdin", action="store_true", help="Read from stdin")
    parser.add_argument("--output", "-o", help="Output MP3 path")
    parser.add_argument("--voice", "-v", default="onyx",
                        choices=["alloy", "ash", "ballad", "coral", "echo",
                                 "fable", "onyx", "nova", "sage", "shimmer"])
    parser.add_argument("--speed", "-s", type=float, default=1.0, help="Speed (0.25-4.0)")
    parser.add_argument("--model", "-m", default="tts-1", choices=["tts-1", "tts-1-hd"])

    args = parser.parse_args()

    # Get text
    if args.stdin or (not args.text and not args.file and not sys.stdin.isatty()):
        text = sys.stdin.read().strip()
    elif args.file:
        text = Path(args.file).read_text().strip()
    elif args.text:
        text = args.text
    else:
        parser.error("Provide text, --file, or --stdin")
        return

    if not text:
        print("No text provided", file=sys.stderr)
        sys.exit(1)

    # Truncate if too long (TTS has a 4096 char limit per call)
    if len(text) > 4096:
        print(f"Warning: Text truncated from {len(text)} to 4096 chars", file=sys.stderr)
        text = text[:4096]

    path = generate_tts(text, voice=args.voice, speed=args.speed,
                        output_path=args.output, model=args.model)
    # Print path to stdout for piping
    print(path)


if __name__ == "__main__":
    main()
