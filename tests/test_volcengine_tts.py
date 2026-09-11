import base64
import json
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.config import Settings
from backend.volcengine_tts import synthesize


def config(**kwargs):
    return Settings(_env_file=None, tts_provider="volcengine", volcengine_tts_api_key="test-only-key", **kwargs)


class Chunks(httpx.AsyncByteStream):
    def __init__(self, parts):
        self.parts = parts
        self.closed = False

    async def __aiter__(self):
        for part in self.parts:
            yield part

    async def aclose(self):
        self.closed = True


def encoded(audio):
    return base64.b64encode(audio).decode("ascii")


@pytest.mark.asyncio
@pytest.mark.parametrize("step", [1, 7, 9999])
async def test_user_contract_and_arbitrary_utf8_json_chunk_boundaries(step):
    wire = (json.dumps({"code": 0, "message": "合成中", "data": encoded(b"MP3-first")}, ensure_ascii=False)
            + '\r\n' + json.dumps({"code": 0, "data": encoded(b"MP3-second")})
            + json.dumps({"code": 20000000})).encode("utf-8")
    stream = Chunks([wire[i:i + step] for i in range(0, len(wire), step)])

    def request(req):
        assert str(req.url) == "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
        assert req.headers["X-Api-Key"] == "test-only-key"
        assert req.headers["X-Api-Resource-Id"] == "seed-tts-2.0"
        assert UUID(req.headers["X-Api-Request-Id"]).version == 4
        assert "Authorization" not in req.headers
        assert json.loads(req.content) == {"req_params": {
            "text": "你好，Hello!", "speaker": "zh_female_sajiaoxuemei_uranus_bigtts",
            "audio_params": {"format": "mp3", "sample_rate": 24000},
        }}
        return httpx.Response(200, stream=stream)

    assert await synthesize(config(), "你好，Hello!", transport=httpx.MockTransport(request)) == (
        b"MP3-firstMP3-second", "audio/mpeg")
    assert stream.closed


@pytest.mark.asyncio
async def test_plain_data_objects_from_example_can_end_at_http_eof():
    data = json.dumps({"data": encoded(b"MP3")})
    audio, mime = await synthesize(config(), "hello", transport=httpx.MockTransport(
        lambda _: httpx.Response(200, text=data)))
    assert audio == b"MP3" and mime == "audio/mpeg"


@pytest.mark.asyncio
@pytest.mark.parametrize("wire", [
    '{"code":0,"data":"bXAz"}',  # A status-based stream must receive its success marker.
    '{"data":"bXAz"',
    '{"code":20000000}',
    '{"code":45000000,"message":"private-test-secret"}',
    '{"data":"not_base64!"}',
    '{"data":123}',
    '[]',
])
async def test_errors_empty_audio_and_truncation_never_return_success(wire):
    with pytest.raises(ValueError) as error:
        await synthesize(config(), "hello", transport=httpx.MockTransport(lambda _: httpx.Response(200, text=wire)))
    assert "private-test-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_size_limit_and_http_failure_close_the_response():
    wire = json.dumps({"data": encoded(b"x" * 2048)}).encode()
    stream = Chunks([wire])
    with pytest.raises(ValueError, match="size limit"):
        await synthesize(config(max_audio_bytes=1024), "hello", transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=stream)))
    assert stream.closed
    with pytest.raises(httpx.HTTPStatusError):
        await synthesize(config(), "hello", transport=httpx.MockTransport(lambda _: httpx.Response(401)))


def test_missing_key_keeps_local_voice_and_reports_pending_without_exposing_secrets(tmp_path):
    cfg = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path.as_posix()}/test.db",
                   tts_provider="volcengine", volcengine_tts_api_key="", windows_tts_enabled=False)
    assert not cfg.tts_ready and not cfg.realtime_ready
    with TestClient(create_app(cfg)) as client:
        cap = client.post("/api/bootstrap").json()["capabilities"]
        assert cap["tts_pending"] is True and cap["tts_provider"] == "browser"
        assert client.post("/api/audio/speech", json={"text": "你好"}).status_code == 503


def test_api_dispatch_returns_mp3_and_sanitizes_provider_errors(tmp_path, monkeypatch):
    from backend import volcengine_tts

    cfg = config(database_url=f"sqlite:///{tmp_path.as_posix()}/test.db")
    wire = json.dumps({"data": encoded(b"MP3-complete")})

    async def mocked_provider(settings, text):
        return await synthesize(settings, text, transport=httpx.MockTransport(lambda _: httpx.Response(200, text=wire)))

    monkeypatch.setattr(volcengine_tts, "synthesize", mocked_provider)
    with TestClient(create_app(cfg)) as client:
        boot = client.post("/api/bootstrap")
        assert boot.json()["capabilities"]["tts_provider"] == "volcengine"
        assert "test-only-key" not in boot.text
        result = client.post("/api/audio/speech", json={"text": "hello"})
        assert result.status_code == 200 and result.content == b"MP3-complete"
        assert result.headers["content-type"] == "audio/mpeg"
        wire = '{"code":45000000,"message":"test-only-key"}'
        error = client.post("/api/audio/speech", json={"text": "hello"})
        assert error.status_code == 502 and "test-only-key" not in error.text


@pytest.mark.asyncio
async def test_livekit_adapter_uses_same_provider_and_mp3_decoder(monkeypatch):
    pytest.importorskip("livekit.agents")
    from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
    from backend import voice_tts

    calls = []

    async def audio(settings, text, **_kwargs):
        assert settings.volcengine_tts_speaker == "zh_female_sajiaoxuemei_uranus_bigtts"
        assert text == "Hello"
        yield b"MP3-a"
        yield b"MP3-b"

    class Emitter:
        def initialize(self, **options):
            assert options["mime_type"] == "audio/mpeg"
            assert options["sample_rate"] == 24000 and options["num_channels"] == 1

        def push(self, data):
            calls.append(data)

        def flush(self):
            calls.append("flushed")

    monkeypatch.setattr(voice_tts, "stream_audio", audio)
    # Exercise the adapter's emission method without starting a room or generating any billable traffic.
    stream = object.__new__(voice_tts.VolcengineStream)
    stream.settings = config()
    stream._input_text = "Hello"
    stream._conn_options = DEFAULT_API_CONNECT_OPTIONS
    await stream._run(Emitter())
    assert calls == [b"MP3-a", b"MP3-b", "flushed"]
