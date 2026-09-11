"""Generate bilingual local audio without playing it or using a remote service."""
import asyncio
import io
import json
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.windows_speech import synthesize_local  # noqa: E402


async def main():
    output = Path(__file__).resolve().parent.parent / "output/qa"
    output.mkdir(parents=True, exist_ok=True)
    result = []
    for language, text in [("zh-CN", "你好，我在这里陪你。"), ("en-US", "Hello. I am here with you.")]:
        audio, content_type = await synthesize_local(text, language)
        with wave.open(io.BytesIO(audio)) as decoded:
            assert decoded.getnframes() > decoded.getframerate()
            result.append({"language": language, "bytes": len(audio), "sample_rate": decoded.getframerate(),
                           "seconds": round(decoded.getnframes() / decoded.getframerate(), 2), "type": content_type})
        (output / f"{language}.wav").write_bytes(audio)
    (output / "speech-smoke.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


asyncio.run(main())
