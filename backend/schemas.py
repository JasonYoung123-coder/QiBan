from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=40)
    user_name: str = Field(default="", max_length=40)
    persona: str = Field(min_length=10, max_length=6000)
    language: Literal["auto", "zh-CN", "en-US"] = "auto"
    character_id: Literal["hiyori", "natori"] = "hiyori"


class ProfileView(ProfileUpdate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    revision: int


class TurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    client_turn_id: str = Field(min_length=8, max_length=70, pattern=r"^[a-zA-Z0-9_-]+$")


class DeliveryRequest(BaseModel):
    generation_id: str
    displayed_text: str = Field(max_length=16000)


class MemoryRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    language: Literal["auto", "zh-CN", "en-US"] = "auto"


class WorkerSync(BaseModel):
    conversation_id: str
    items: list[dict] = Field(max_length=200)
