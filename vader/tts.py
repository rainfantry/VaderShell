"""
22DIV — TalkyTalk TTS bridge for Discord.

Wraps George's existing `talkytalk/talkytalk.py` so the async gateway can fire
voice without blocking the bot loop. Generates an MP3 and returns its path so
`gateway_discord.py` can attach it to a Discord message.

Reads the same .env as VaderShell (ELEVENLABS_API_KEY is reused if present).
Falls back to Windows SAPI if offline or no key. Logs failures silently so a
TTS glitch never kills chat.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("vader.tts")

_TALKYTALK = Path("C:/Users/gwu07/machine-spirit/talkytalk/talkytalk.py")
_VADER_VOICE_ID = "twLPF55UcxNYRmxaWLAn"  # from George's talkytalk config


def _is_online() -> bool:
    try:
        import socket
        socket.create_connection(("api.elevenlabs.io", 443), timeout=2)
        return True
    except OSError:
        return False


def _load_elevenlabs_key() -> Optional[str]:
    """Reuse the VaderShell env if present; otherwise look for the TalkyTalk .env."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if key:
        return key
    env_file = Path("C:/Users/gwu07/machine-spirit/talkytalk/.env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("ELEVENLABS_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"\'')
    return None


def _filter_for_voice(text: str) -> str:
    """Strip markdown/code so it sounds like speech, not a Discord message."""
    import re
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]*)\*", r"\1", text)
    text = re.sub(r"https?://\S+", "link", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _speak_with_talkytalk(text: str) -> Optional[Path]:
    """Call the standalone TalkyTalk script synchronously. Return the MP3 path."""
    if not _TALKYTALK.exists():
        log.warning("TalkyTalk script not found at %s", _TALKYTALK)
        return None

    # TalkyTalk expects the text as a CLI arg. It writes to ~/.talkytalk/voice/.
    try:
        result = subprocess.run(
            [sys.executable, str(_TALKYTALK), text],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.warning("TalkyTalk failed: %s", result.stderr or result.stdout)
            return None
    except subprocess.TimeoutExpired:
        log.warning("TalkyTalk timed out")
        return None
    except Exception as e:
        log.warning("TalkyTalk error: %s", e)
        return None

    # TalkyTalk prints the path on success; fall back to scanning the voice dir.
    voice_dir = Path.home() / ".talkytalk" / "voice"
    if not voice_dir.exists():
        return None

    # Find the newest MP3 created in the last minute.
    candidates = sorted(
        [p for p in voice_dir.glob("*.mp3") if p.stat().st_mtime > time.time() - 60],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _speak_with_elevenlabs_direct(text: str) -> Optional[Path]:
    """Minimal inline ElevenLabs fallback (no external script)."""
    key = _load_elevenlabs_key()
    if not key:
        return None
    try:
        # Lazy import so the bot starts even if the package isn't installed.
        from elevenlabs.client import ElevenLabs
        from elevenlabs import VoiceSettings

        client = ElevenLabs(api_key=key)
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=_VADER_VOICE_ID,
            model_id="eleven_turbo_v2_5",
            voice_settings=VoiceSettings(
                stability=0.42,
                similarity_boost=0.78,
                style=0.92,
                use_speaker_boost=True,
            ),
        )
        tmp = Path(tempfile.gettempdir()) / f"vader_tts_{int(time.time()*1000)}.mp3"
        with open(tmp, "wb") as f:
            for chunk in audio:
                f.write(chunk)
        return tmp
    except Exception as e:
        log.warning("Direct ElevenLabs TTS failed: %s", e)
        return None


def _speak_with_sapi(text: str) -> Optional[Path]:
    """Windows SAPI fallback — writes a WAV file via PowerShell."""
    if sys.platform != "win32":
        return None
    tmp = Path(tempfile.gettempdir()) / f"vader_sapi_{int(time.time()*1000)}.wav"
    ps = f'''
    Add-Type -AssemblyName System.Speech
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $synth.SetOutputToWaveFile("{tmp}")
    $synth.Speak("{text.replace('"', "'")}")
    $synth.Dispose()
    '''
    try:
        subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=30)
        return tmp if tmp.exists() else None
    except Exception as e:
        log.warning("SAPI fallback failed: %s", e)
        return None


def speak(text: str) -> Optional[Path]:
    """Generate voice for `text` and return the path to the audio file."""
    text = _filter_for_voice(text)
    if not text:
        log.info("TTS skipped: empty after filtering")
        return None

    # Keep it short enough for Discord attachments and ElevenLabs limits.
    if len(text) > 1500:
        text = text[:1497] + "..."

    log.info("TTS: generating voice for %d chars", len(text))

    # 1. Prefer the existing TalkyTalk script (reuses slang expansion, voice settings, etc.)
    path = _speak_with_talkytalk(text)
    if path and path.exists():
        return path

    # 2. Direct ElevenLabs if online and key available
    if _is_online() and _load_elevenlabs_key():
        path = _speak_with_elevenlabs_direct(text)
        if path and path.exists():
            return path

    # 3. Windows SAPI fallback
    path = _speak_with_sapi(text)
    if path and path.exists():
        return path

    log.warning("TTS: all engines failed")
    return None


async def speak_async(text: str) -> Optional[Path]:
    """Async wrapper for use in the Discord gateway."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, speak, text)
