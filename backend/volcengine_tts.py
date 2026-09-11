"""Volcengine V3 unidirectional TTS: UTF-8 JSON objects carrying base64 MP3 chunks."""
import base64
import binascii
import codecs
import json
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx

from .config import Settings


async def stream_audio(settings: Settings, text: str, *, transport: httpx.AsyncBaseTransport | None = None,
                       timeout: float = 45) -> AsyncIterator[bytes]:
    if not settings.volcengine_tts_api_key.strip():
        raise ValueError("Volcengine TTS key is not configured")
    headers = {
        "X-Api-Key": settings.volcengine_tts_api_key,
        "X-Api-Resource-Id": settings.volcengine_tts_resource_id,
        "X-Api-Request-Id": str(uuid4()),
        "Content-Type": "application/json",
    }
    payload = {"req_params": {
        "text": text, "speaker": settings.volcengine_tts_speaker,
        "audio_params": {"format": "mp3", "sample_rate": 24000},
    }}
    decoder = json.JSONDecoder()
    utf8 = codecs.getincrementaldecoder("utf-8")()
    pending = ""
    audio_size = 0
    saw_status = False
    finished = False
    # Encoded MP3 can be larger than decoded audio; bound incomplete/malformed JSON too.
    wire_limit = settings.max_audio_bytes * 2 + 65536
    wire_size = 0

    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        async with client.stream("POST", settings.volcengine_tts_url, headers=headers, json=payload) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                wire_size += len(chunk)
                if wire_size > wire_limit:
                    raise ValueError("Volcengine response exceeded size limit")
                pending += utf8.decode(chunk)
                while pending.strip():
                    pending = pending.lstrip()
                    try:
                        event, end = decoder.raw_decode(pending)
                    except json.JSONDecodeError:
                        break  # Network chunks do not necessarily end at a JSON object boundary.
                    pending = pending[end:]
                    if not isinstance(event, dict):
                        raise ValueError("Invalid Volcengine event")
                    code = event.get("code")
                    saw_status |= code is not None
                    if code not in (None, 0, 20000000):
                        # Never surface the provider's message/body: it can contain input or credentials.
                        raise ValueError("Volcengine reported a synthesis error")
                    data = event.get("data")
                    if data:
                        if not isinstance(data, str):
                            raise ValueError("Invalid Volcengine audio data")
                        try:
                            audio = base64.b64decode(data, validate=True)
                        except (binascii.Error, ValueError):
                            raise ValueError("Invalid Volcengine base64 audio") from None
                        audio_size += len(audio)
                        if audio_size > settings.max_audio_bytes:
                            raise ValueError("Volcengine audio exceeded size limit")
                        if audio:
                            yield audio
                    if code == 20000000:
                        finished = True
                        break
                if finished:
                    break
            pending += utf8.decode(b"", final=True)
    if pending.strip():
        raise ValueError("Incomplete or unexpected Volcengine JSON data")
    if saw_status and not finished:
        raise ValueError("Volcengine stream ended without success status")
    if not audio_size:
        raise ValueError("Volcengine returned no audio")


async def synthesize(settings: Settings, text: str, *, transport: httpx.AsyncBaseTransport | None = None
                     ) -> tuple[bytes, str]:
    audio = bytearray()
    async for chunk in stream_audio(settings, text, transport=transport):
        audio.extend(chunk)
    return bytes(audio), "audio/mpeg"
