"""LiveKit adapter for the same Volcengine voice used by desktop reply playback."""
import httpx
from livekit.agents import APIConnectionError, APIConnectOptions, tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from uuid import uuid4

from .config import Settings
from .volcengine_tts import stream_audio


class VolcengineTTS(tts.TTS):
    def __init__(self, settings: Settings):
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False), sample_rate=24000, num_channels=1)
        self.settings = settings

    @property
    def model(self) -> str:
        return self.settings.volcengine_tts_resource_id

    @property
    def provider(self) -> str:
        return "volcengine"

    def synthesize(self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS):
        return VolcengineStream(tts=self, input_text=text, conn_options=conn_options)


class VolcengineStream(tts.ChunkedStream):
    def __init__(self, *, tts: VolcengineTTS, input_text: str, conn_options: APIConnectOptions):
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self.settings = tts.settings

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(request_id=str(uuid4()), sample_rate=24000, num_channels=1, mime_type="audio/mpeg")
        try:
            async for chunk in stream_audio(self.settings, self.input_text, timeout=self._conn_options.timeout):
                output_emitter.push(chunk)
            output_emitter.flush()
        except (httpx.HTTPError, ValueError):
            raise APIConnectionError("Volcengine speech synthesis failed") from None
