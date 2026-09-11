from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str = f"sqlite:///{(ROOT / '.data' / 'companion.db').as_posix()}"
    chat_base_url: str = ""
    chat_provider: Literal["openai", "responses", "anthropic"] = "openai"
    chat_model: str = ""
    chat_api_key: str = ""
    chat_timeout_seconds: float = 60
    chat_require_api_key: bool = True
    chat_max_tokens: int = 0
    stt_base_url: str = ""
    stt_model: str = ""
    stt_api_key: str = ""
    tts_base_url: str = ""
    tts_model: str = ""
    tts_voice: str = "alloy"
    tts_api_key: str = ""
    tts_provider: Literal["openai", "volcengine", "system"] = "openai"
    volcengine_tts_url: str = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
    volcengine_tts_api_key: str = ""
    volcengine_tts_resource_id: str = "seed-tts-2.0"
    volcengine_tts_speaker: str = "zh_female_sajiaoxuemei_uranus_bigtts"
    windows_tts_enabled: bool = True
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    worker_secret: str = ""
    app_origins: str = "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:18765,http://localhost:18765"
    max_audio_bytes: int = Field(default=12_000_000, ge=1024)
    demo_chunk_delay: float = 0.025

    @property
    def chat_ready(self) -> bool:
        return bool(self.chat_base_url and self.chat_model and (self.chat_api_key or not self.chat_require_api_key))

    @property
    def stt_ready(self) -> bool:
        return bool(self.stt_base_url and self.stt_model)

    @property
    def tts_ready(self) -> bool:
        if self.tts_provider == "system":
            return False
        if self.tts_provider == "volcengine":
            return bool(self.volcengine_tts_api_key.strip() and self.volcengine_tts_url
                        and self.volcengine_tts_resource_id and self.volcengine_tts_speaker)
        return bool(self.tts_base_url and self.tts_model)

    @property
    def realtime_ready(self) -> bool:
        return all((self.livekit_url, self.livekit_api_key, self.livekit_api_secret,
                    self.worker_secret, self.chat_ready, self.stt_ready, self.tts_ready))
