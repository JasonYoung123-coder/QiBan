"""Use the same text-only provider contract for chat and the optional voice worker."""
from uuid import uuid4

import httpx
from livekit.agents import APIError, DEFAULT_API_CONNECT_OPTIONS, llm

from .providers import ChatProvider


class CompanionLLM(llm.LLM):
    def __init__(self, settings, transport=None):
        super().__init__()
        self.chat_provider = ChatProvider(settings, transport)

    @property
    def model(self):
        return self.chat_provider.settings.chat_model

    @property
    def provider(self):
        return self.chat_provider.settings.chat_provider

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **kwargs):
        if tools:
            raise ValueError("Companion voice supports text conversation only")
        return CompanionStream(self, chat_ctx=chat_ctx, tools=[], conn_options=conn_options)


class CompanionStream(llm.LLMStream):
    async def _run(self):
        messages = [{"role": item.role, "content": item.text_content}
                    for item in self.chat_ctx.items if isinstance(item, llm.ChatMessage)
                    and item.role in ("system", "developer", "user", "assistant") and item.text_content]
        request_id = str(uuid4())
        try:
            async for text in self._llm.chat_provider.stream(messages, name="栖伴", language="auto", memories=[]):
                self._event_ch.send_nowait(llm.ChatChunk(
                    id=request_id, delta=llm.ChoiceDelta(role="assistant", content=text)))
        except (httpx.HTTPError, ValueError):
            # Avoid logging remote response bodies/credentials or replaying an already-spoken prefix.
            raise APIError("Companion model request failed; check connection settings", retryable=False) from None
