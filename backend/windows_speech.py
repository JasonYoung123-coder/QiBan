"""Local Windows SAPI speech, including voices not exposed by Chromium's speechSynthesis."""
import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path

from .config import ROOT

POWERSHELL = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


def available() -> bool:
    return os.name == "nt" and POWERSHELL.is_file()


async def synthesize_local(text: str, language: str) -> tuple[bytes, str]:
    with tempfile.TemporaryDirectory(prefix="qiban-speech-") as directory:
        output = Path(directory) / "speech.wav"
        payload = json.dumps({"text": text, "language": language, "output": str(output)}, ensure_ascii=False)
        process = await asyncio.create_subprocess_exec(
            str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(ROOT / "scripts/windows-speech.ps1"),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            await asyncio.wait_for(process.communicate(payload.encode("utf-8")), timeout=45)
            if process.returncode or not output.is_file():
                raise ValueError("Windows voice for the requested language is unavailable")
            audio = output.read_bytes()
            if len(audio) < 44 or len(audio) > 12_000_000 or not audio.startswith(b"RIFF"):
                raise ValueError("Invalid Windows speech output")
            return audio, "audio/wav"
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
