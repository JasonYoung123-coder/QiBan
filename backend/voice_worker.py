"""Optional LiveKit worker. One SDK session owns turn detection, ASR, generation, TTS and interruption.

Run: python -m backend.voice_worker download-files, then python -m backend.voice_worker dev.
Real service configuration is required; this module never substitutes a simulated voice conversation.
"""
import asyncio
import contextlib
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import httpx
from livekit import agents
from livekit.agents import Agent, AgentSession, JobContext, llm, room_io
from livekit.plugins import openai, silero
from sqlalchemy import select

from .config import ROOT, Settings
from .database import Message, Profile, make_database
from .providers import compile_persona
from .voice_tts import VolcengineTTS

cfg = Settings()
server = agents.AgentServer(ws_url=cfg.livekit_url or None, api_key=cfg.livekit_api_key or None,
                            api_secret=cfg.livekit_api_secret or None, log_level="INFO")


class CompanionVoiceAgent(Agent):
    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage):
        # Without verified phoneme/word alignment, an interrupted assistant message is conservatively omitted.
        # This sacrifices recall of the heard prefix instead of treating an unplayed suffix as delivered.
        turn_ctx.items[:] = [item for item in turn_ctx.items
                             if not (isinstance(item, llm.ChatMessage) and item.role == "assistant" and item.interrupted)]


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    if not cfg.realtime_ready:
        raise RuntimeError("Complete LiveKit, chat, STT, TTS and WORKER_SECRET configuration first.")
    room_name = ctx.room.name
    if not room_name.startswith("qiban-"):
        ctx.shutdown("not_a_companion_room")
        return
    endpoint = f"http://127.0.0.1:18765/api/internal/voice/{room_name}"
    http = httpx.AsyncClient(headers={"Authorization": f"Bearer {cfg.worker_secret}"}, timeout=5)
    context_response = await http.get(endpoint)
    context_response.raise_for_status()
    payload = context_response.json()
    owner_id = payload["profile"]["id"]
    revision = payload["profile"]["revision"]
    conversation_id = payload["conversation_id"]
    (ROOT / ".data").mkdir(exist_ok=True)
    engine, sessions = make_database(cfg.database_url)
    with sessions() as db:
        profile = db.get(Profile, owner_id)
        if not profile or profile.revision != revision:
            raise RuntimeError("Voice context expired before connection")
        previous = list(db.scalars(select(Message).where(Message.conversation_id == conversation_id,
                                                         Message.context_revision == revision)
                                   .order_by(Message.created_at.desc()).limit(30)))
    chat_ctx = llm.ChatContext()
    for row in reversed(previous):
        if row.delivered_text:
            chat_ctx.add_message(role=row.role, content=row.delivered_text)
    language = "Follow the user's language, Chinese or English" if profile.language == "auto" else profile.language
    agent = CompanionVoiceAgent(instructions=compile_persona(profile, payload["memories"], language), chat_ctx=chat_ctx)
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=openai.STT(base_url=cfg.stt_base_url, api_key=cfg.stt_api_key or "local-not-required",
                       model=cfg.stt_model, language="zh" if profile.language == "zh-CN" else "en",
                       detect_language=profile.language == "auto", use_realtime=False),
        llm=openai.LLM(base_url=cfg.chat_base_url, api_key=cfg.chat_api_key or "local-not-required", model=cfg.chat_model),
        tts=VolcengineTTS(cfg) if cfg.tts_provider == "volcengine" else openai.TTS(
            base_url=cfg.tts_base_url, api_key=cfg.tts_api_key or "local-not-required",
            model=cfg.tts_model, voice=cfg.tts_voice, response_format="wav"),
        turn_detection="vad", allow_interruptions=True, min_interruption_duration=0.35,
        min_interruption_words=1, min_endpointing_delay=0.55, max_endpointing_delay=2,
    )

    @session.on("conversation_item_added")
    def persist_item(event):
        item = event.item
        if not isinstance(item, llm.ChatMessage) or item.role not in ("user", "assistant"):
            return
        text = item.text_content or ""
        if not text:
            return
        stable_id = str(uuid5(NAMESPACE_URL, f"{room_name}/{item.id}"))
        with sessions() as db:
            current = db.get(Profile, owner_id)
            if not current or current.revision != revision:
                return
            row = db.get(Message, stable_id)
            if row is None:
                row = Message(id=stable_id, conversation_id=conversation_id, client_turn_id=f"voice-{stable_id}",
                              generation_id=stable_id if item.role == "assistant" else "", role=item.role,
                              context_revision=revision, created_at=datetime.fromtimestamp(item.created_at, UTC).isoformat())
                db.add(row)
            row.generated_text = text
            row.delivered_text = "" if item.role == "assistant" and item.interrupted else text
            row.delivery_state = "interrupted" if item.interrupted else "delivered"
            db.commit()

    @session.on("close")
    def session_closed(_event):
        ctx.shutdown("voice_session_closed")

    async def watch_lease():
        while True:
            await asyncio.sleep(0.75)
            try:
                response = await http.get(endpoint)
                if response.status_code == 200:
                    continue
            except httpx.HTTPError:
                pass
            session.interrupt()
            await session.aclose()
            ctx.shutdown("voice_lease_ended")
            return

    watch_task = None

    async def cleanup():
        if watch_task:
            watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watch_task
        await session.aclose()
        await http.aclose()
        engine.dispose()

    ctx.add_shutdown_callback(cleanup)
    await ctx.connect()
    await ctx.wait_for_participant(identity=owner_id)
    await session.start(agent=agent, room=ctx.room,
                        room_options=room_io.RoomOptions(participant_identity=owner_id))
    watch_task = asyncio.create_task(watch_lease())


if __name__ == "__main__":
    agents.cli.run_app(server)
