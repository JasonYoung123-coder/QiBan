"""Portable local connection settings. Secrets are write-only in the HTTP API."""
import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .config import Settings

Provider = Literal["openai", "responses", "anthropic"]
DEFAULT_URLS = {"openai": "https://api.openai.com/v1", "responses": "https://api.openai.com/v1",
                "anthropic": "https://api.anthropic.com/v1"}


def clean_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return value
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https", "ws", "wss") or not parsed.hostname:
        raise ValueError("请输入完整服务地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("服务地址不能包含账号、密钥、查询参数或片段")
    if parsed.scheme in ("http", "ws") and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("远程服务请使用 HTTPS 或 WSS")
    return value


class ChatConnection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    base_url: str = Field(max_length=2048)
    model: str = Field(max_length=200)
    api_key: SecretStr | None = Field(default=None, max_length=4096)
    require_api_key: bool = True
    max_tokens: int = Field(default=0, ge=0, le=128000)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value):
        value = clean_url(value)
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("聊天地址请使用 HTTP 或 HTTPS")
        for suffix in ("/chat/completions", "/responses", "/messages"):
            if value.endswith(suffix):
                value = value[:-len(suffix)]
        return value


class VoiceConnection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tts_provider: Literal["system", "volcengine", "openai"] = "volcengine"
    volcengine_tts_url: str = Field(default="https://openspeech.bytedance.com/api/v3/tts/unidirectional", max_length=2048)
    volcengine_tts_api_key: SecretStr | None = Field(default=None, max_length=4096)
    volcengine_tts_resource_id: str = Field(default="seed-tts-2.0", max_length=200)
    volcengine_tts_speaker: str = Field(default="zh_female_sajiaoxuemei_uranus_bigtts", max_length=200)
    tts_base_url: str = Field(default="", max_length=2048)
    tts_model: str = Field(default="", max_length=200)
    tts_voice: str = Field(default="", max_length=200)
    tts_api_key: SecretStr | None = Field(default=None, max_length=4096)
    stt_base_url: str = Field(default="", max_length=2048)
    stt_model: str = Field(default="", max_length=200)
    stt_api_key: SecretStr | None = Field(default=None, max_length=4096)
    livekit_url: str = Field(default="", max_length=2048)
    livekit_api_key: SecretStr | None = Field(default=None, max_length=4096)
    livekit_api_secret: SecretStr | None = Field(default=None, max_length=4096)
    worker_secret: SecretStr | None = Field(default=None, max_length=4096)

    @field_validator("volcengine_tts_url", "tts_base_url", "stt_base_url", "livekit_url")
    @classmethod
    def validate_url(cls, value, info):
        value = clean_url(value)
        allowed = ("ws://", "wss://") if info.field_name == "livekit_url" else ("http://", "https://")
        if value and not value.startswith(allowed):
            raise ValueError("服务地址协议不匹配")
        return value


class ConnectionsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    chat_provider: Provider
    chats: dict[Provider, ChatConnection]
    voice: VoiceConnection


class SettingsConflict(ValueError):
    pass


class ConnectionStore:
    def __init__(self, cfg: Settings, path: Path | None = None):
        self.path = path
        self.document = {"revision": 1, "chat_provider": cfg.chat_provider,
                         "chats": {provider: {"base_url": url, "model": "", "api_key": "",
                                               "require_api_key": True, "max_tokens": 0}
                                   for provider, url in DEFAULT_URLS.items()},
                         "voice": {key: getattr(cfg, key) for key in VoiceConnection.model_fields}}
        self.document["chats"][cfg.chat_provider].update(
            base_url=cfg.chat_base_url or DEFAULT_URLS[cfg.chat_provider], model=cfg.chat_model, api_key=cfg.chat_api_key,
            require_api_key=cfg.chat_require_api_key, max_tokens=cfg.chat_max_tokens)
        if path and path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                checked = ConnectionsUpdate.model_validate(raw)
                self.document = self._merged(checked, initial=True)
            except (ValueError, OSError):
                raise RuntimeError("连接设置文件无法读取，请检查 .data/connections.json。") from None

    def public(self) -> dict:
        result = copy.deepcopy(self.document)
        for group in [*result["chats"].values(), result["voice"]]:
            for key in list(group):
                if key != "require_api_key" and key.endswith(("api_key", "api_secret", "worker_secret")):
                    group[f"{key}_set"] = bool(group.pop(key))
        return result

    def _merged(self, update: ConnectionsUpdate, *, initial=False) -> dict:
        if not initial and update.revision != self.document["revision"]:
            raise SettingsConflict("设置已被其他窗口更新，请重新载入后保存。")
        if set(update.chats) != set(DEFAULT_URLS):
            raise ValueError("请提供全部接口配置")
        result = copy.deepcopy(self.document)
        result["chat_provider"] = update.chat_provider
        result["revision"] = update.revision
        for old, new in [(result["chats"][p], c) for p, c in update.chats.items()] + [(result["voice"], update.voice)]:
            values = new.model_dump()
            # Retained credentials must never silently travel to an edited endpoint.
            pairs = [("base_url", "api_key"), ("tts_base_url", "tts_api_key"), ("stt_base_url", "stt_api_key"),
                     ("volcengine_tts_url", "volcengine_tts_api_key"), ("livekit_url", "livekit_api_secret"),
                     ("livekit_url", "livekit_api_key")]
            for url, key in pairs:
                if not initial and url in values and values[url] != old.get(url) and old.get(key) and values.get(key) is None:
                    raise ValueError("更换服务地址时，请重新填写对应密钥，或勾选清除旧密钥。")
            for key, value in values.items():
                if isinstance(value, SecretStr):
                    old[key] = value.get_secret_value().strip()
                elif value is not None:
                    old[key] = value
        return result

    def apply(self, cfg: Settings, document: dict | None = None) -> Settings:
        data = document or self.document
        chat = data["chats"][data["chat_provider"]]
        values = {"chat_provider": data["chat_provider"], "chat_base_url": chat["base_url"],
                  "chat_model": chat["model"], "chat_api_key": chat["api_key"],
                  "chat_require_api_key": chat["require_api_key"], "chat_max_tokens": chat["max_tokens"],
                  **data["voice"]}
        return cfg.model_copy(update=values, deep=True)

    def preview(self, update: ConnectionsUpdate, cfg: Settings) -> Settings:
        return self.apply(cfg, self._merged(update))

    def save(self, update: ConnectionsUpdate):
        document = self._merged(update)
        document["revision"] += 1
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(prefix="connections-", suffix=".tmp", dir=self.path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                    json.dump(document, file, ensure_ascii=False, indent=2)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(name, self.path)
            finally:
                Path(name).unlink(missing_ok=True)
        self.document = document
