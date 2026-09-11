import asyncio
import contextlib
import json
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from sqlalchemy import select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import ROOT, Settings
from .connection_settings import ConnectionStore, ConnectionsUpdate, SettingsConflict
from .database import Conversation, Memory, Message, Profile, make_database, new_session_token, token_hash
from .providers import ChatProvider, compile_persona, language_for, synthesize, transcribe
from .schemas import DeliveryRequest, MemoryRequest, ProfileUpdate, ProfileView, SpeechRequest, TurnRequest
from .windows_speech import available as windows_speech_available, synthesize_local


@dataclass
class Generation:
    owner: str
    conversation: str
    message: str
    id: str
    revision: int
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    task: asyncio.Task | None = None
    text: str = ""
    sequence: int = 0

    def emit(self, kind: str, payload: dict):
        self.sequence += 1
        self.queue.put_nowait({"type": kind, "generation_id": self.id,
                               "conversation_id": self.conversation, "session_epoch": self.revision,
                               "sequence": self.sequence, "payload": payload})


def create_app(settings: Settings | None = None, provider: ChatProvider | None = None,
               settings_store: ConnectionStore | None = None) -> FastAPI:
    base_cfg = settings or Settings()
    store = settings_store or ConnectionStore(base_cfg, None if settings else ROOT / ".data/connections.json")
    cfg = store.apply(base_cfg)
    (ROOT / ".data").mkdir(exist_ok=True)
    engine, sessions = make_database(cfg.database_url)
    chat = provider or ChatProvider(cfg)
    active: dict[str, Generation] = {}
    voice_leases: dict[str, dict] = {}
    local_tts = cfg.windows_tts_enabled and windows_speech_available()

    def cancel_owner(owner: str):
        for generation in list(active.values()):
            if generation.owner == owner and generation.task:
                generation.task.cancel()
        for conversation_id, lease in list(voice_leases.items()):
            if lease["owner"] == owner:
                voice_leases.pop(conversation_id, None)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        tasks = [g.task for g in active.values() if g.task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        engine.dispose()

    app = FastAPI(title="Qiban Companion Core", version="0.2.0", lifespan=lifespan)
    app.state.sessions = sessions
    app.state.settings = cfg
    app.state.generations = active
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc):
        # Pydantic's default response echoes invalid input, which may contain an API key.
        return JSONResponse({"detail": [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
                                        for error in exc.errors()]}, status_code=422)

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        # This bootstrap is for a loopback-only personal prototype, not public account login.
        # Origin checks block another web page from mutating local memory via the browser.
        origin = request.headers.get("origin")
        if request.url.path.startswith("/api/") and origin and origin not in cfg.app_origins.split(","):
            return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    def actor(request: Request) -> Profile:
        token = request.cookies.get("qiban_session", "")
        if not token or len(token) > 200:
            raise HTTPException(401, "请刷新页面建立本地会话。")
        with sessions() as db:
            profile = db.scalar(select(Profile).where(Profile.session_hash == token_hash(token)))
            if not profile:
                raise HTTPException(401, "本地会话已失效，请刷新页面。")
            return profile

    def owned_conversation(db, conversation_id: str, owner: str) -> Conversation:
        conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id,
                                                             Conversation.owner_id == owner))
        if not conversation:
            raise HTTPException(404, "找不到这段会话。")
        return conversation

    def profile_view(profile):
        return ProfileView.model_validate(profile).model_dump()

    def message_view(message):
        return {"id": message.id, "role": message.role, "text": message.delivered_text,
                "delivery_state": message.delivery_state, "generation_id": message.generation_id,
                "created_at": message.created_at}

    @app.get("/api/health")
    async def health():
        import hashlib
        return {"ok": True, "version": "0.2.0", "service": "qiban-companion-core",
                "instance": hashlib.sha256(ROOT.as_posix().lower().encode()).hexdigest()[:16]}

    def capabilities():
        return {"chat": "connected" if cfg.chat_ready else "demo", "chat_provider": cfg.chat_provider,
                "stt": cfg.stt_ready, "tts": cfg.tts_ready or local_tts,
                "tts_provider": ("volcengine" if cfg.tts_provider == "volcengine" else "remote")
                if cfg.tts_ready else "windows" if local_tts else "browser",
                "tts_pending": cfg.tts_provider == "volcengine" and not cfg.tts_ready,
                "realtime": cfg.realtime_ready, "model": cfg.chat_model if cfg.chat_ready else ""}

    @app.get("/api/settings")
    async def connection_settings(request: Request):
        actor(request)
        return {"settings": store.public(), "capabilities": capabilities()}

    @app.put("/api/settings")
    async def save_connections(body: ConnectionsUpdate, request: Request):
        nonlocal cfg, chat, local_tts
        actor(request)
        try:
            store.save(body)
        except SettingsConflict as error:
            raise HTTPException(409, str(error)) from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        except OSError:
            raise HTTPException(500, "无法保存设置，请把应用放在可写的文件夹中。") from None
        for owner in {g.owner for g in active.values()} | {lease["owner"] for lease in voice_leases.values()}:
            cancel_owner(owner)
        cfg = store.apply(base_cfg)
        app.state.settings = cfg
        chat = ChatProvider(cfg)
        local_tts = cfg.windows_tts_enabled and windows_speech_available()
        return {"settings": store.public(), "capabilities": capabilities()}

    @app.post("/api/settings/test")
    async def test_connection(body: ConnectionsUpdate, request: Request):
        actor(request)
        try:
            candidate = store.preview(body, base_cfg)
            if not candidate.chat_ready:
                raise HTTPException(422, "请填写服务地址、模型名称和 API Key。")
            candidate.chat_timeout_seconds = min(candidate.chat_timeout_seconds, 20)
            preview = ChatProvider(candidate)
            async def check():
                answer = ""
                async for part in preview.stream([{"role": "user", "content": "Reply with OK."}],
                                                  name="connection-test", language="en-US", memories=[]):
                    answer += part
                    if len(answer) > 1000:
                        return True
                return bool(answer.strip())
            if not await asyncio.wait_for(check(), timeout=25):
                raise ValueError("Empty response")
        except SettingsConflict as error:
            raise HTTPException(409, str(error)) from None
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            hint = "请检查密钥和账号权限。" if status in (401, 403) else "请检查服务地址、模型名称、配额或接口类型。"
            raise HTTPException(502, f"服务返回 HTTP {status}，{hint}") from None
        except (httpx.HTTPError, ValueError, TimeoutError):
            raise HTTPException(502, "连接测试未通过，请检查接口类型、地址、模型或网络。") from None
        return {"ok": True, "message": "连接成功，模型已返回文字。"}

    @app.post("/api/bootstrap")
    async def bootstrap(request: Request, response: Response):
        try:
            profile = actor(request)
        except HTTPException:
            token = new_session_token()
            with sessions() as db:
                profile = Profile(session_hash=token_hash(token))
                db.add(profile)
                db.commit()
            response.set_cookie("qiban_session", token, httponly=True, samesite="strict", max_age=2592000)
        with sessions() as db:
            conversation = db.scalar(select(Conversation).where(Conversation.owner_id == profile.id)
                                     .order_by(Conversation.created_at.desc()))
            if conversation is None:
                conversation = Conversation(owner_id=profile.id)
                db.add(conversation)
                db.commit()
        return {"profile": profile_view(profile), "conversation_id": conversation.id,
                "capabilities": capabilities()}

    @app.put("/api/profile")
    async def update_profile(body: ProfileUpdate, request: Request):
        owner = actor(request)
        cancel_owner(owner.id)
        with sessions() as db:
            profile = db.get(Profile, owner.id)
            for key, value in body.model_dump().items():
                setattr(profile, key, value.strip())
            profile.revision += 1
            db.commit()
            return profile_view(profile)

    @app.post("/api/conversations")
    async def new_conversation(request: Request):
        owner = actor(request)
        cancel_owner(owner.id)
        with sessions() as db:
            conversation = Conversation(owner_id=owner.id)
            db.add(conversation)
            db.commit()
            return {"id": conversation.id}

    @app.get("/api/conversations/{conversation_id}/messages")
    async def messages(conversation_id: str, request: Request):
        owner = actor(request)
        with sessions() as db:
            owned_conversation(db, conversation_id, owner.id)
            rows = db.scalars(select(Message).where(Message.conversation_id == conversation_id)
                              .order_by(Message.created_at)).all()
            return [message_view(row) for row in rows if row.delivered_text]

    async def produce(g: Generation, prompt: list[dict[str, str]], profile, language, memories, reply_provider):
        state = "generated"
        try:
            g.emit("assistant.started", {"message_id": g.message, "language": language,
                                          "mode": "connected" if cfg.chat_ready else "demo"})
            async for delta in reply_provider.stream(prompt, name=profile.name, language=language, memories=memories):
                if len(g.text) + len(delta) > 16000:
                    raise ValueError("Reply exceeded length limit")
                g.text += delta
                g.emit("assistant.delta", {"text": delta})
            if not g.text.strip():
                raise ValueError("Provider returned an empty reply")
            g.emit("assistant.generated", {"message_id": g.message, "text": g.text, "language": language})
        except asyncio.CancelledError:
            state = "interrupted"
            g.emit("assistant.interrupted", {})
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            state = "failed"
            # Provider errors may contain credentials or prompts. Expose a bounded diagnostic only.
            g.emit("assistant.error", {"message": "聊天服务没有完成回复。请检查本地配置、模型名称与网络后重试。"})
        finally:
            with sessions() as db:
                row = db.get(Message, g.message)
                row.generated_text = g.text
                if row.delivery_state not in ("delivered", "interrupted"):
                    row.delivery_state = state
                db.commit()
            g.queue.put_nowait(None)
            if active.get(g.conversation) is g:
                active.pop(g.conversation, None)

    @app.post("/api/conversations/{conversation_id}/turns")
    async def turn(conversation_id: str, body: TurnRequest, request: Request):
        profile = actor(request)
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "请输入想说的话。")
        # All DB checks and registration below run before the first await. One local process owns generations.
        with sessions() as db:
            conversation = owned_conversation(db, conversation_id, profile.id)
            existing = db.scalar(select(Message).where(Message.conversation_id == conversation_id,
                                                       Message.client_turn_id == body.client_turn_id,
                                                       Message.role == "user"))
            if existing:
                raise HTTPException(409, "这一条消息已经提交，请刷新会话查看结果。")
            if conversation_id in active:
                raise HTTPException(409, "请先停止当前回复。")
            lease = voice_leases.get(conversation_id)
            if lease and lease["expires"] > time.monotonic():
                raise HTTPException(409, "请先结束这段实时通话。")
            memories = list(db.scalars(select(Memory.text).where(Memory.owner_id == profile.id)
                                      .order_by(Memory.created_at).limit(20)))
            history = list(db.scalars(select(Message).where(Message.conversation_id == conversation_id,
                                                           Message.context_revision == profile.revision)
                                     .order_by(Message.created_at.desc()).limit(30)))
            language = language_for(text, profile.language)
            prompt = [{"role": "system", "content": compile_persona(profile, memories, language)}]
            prompt.extend({"role": row.role, "content": row.delivered_text}
                          for row in reversed(history) if row.delivered_text)
            prompt.append({"role": "user", "content": text})
            generation_id = str(uuid4())
            user = Message(conversation_id=conversation_id, client_turn_id=body.client_turn_id, role="user",
                           generated_text=text, delivered_text=text, delivery_state="delivered",
                           context_revision=profile.revision)
            assistant = Message(conversation_id=conversation_id, client_turn_id=body.client_turn_id,
                                role="assistant", generation_id=generation_id, context_revision=profile.revision)
            db.add_all([user, assistant])
            if conversation.title == "新的相伴":
                conversation.title = text[:80]
            db.commit()
            g = Generation(profile.id, conversation_id, assistant.id, generation_id, profile.revision)
            active[conversation_id] = g
        g.task = asyncio.create_task(produce(g, prompt, profile, language, memories, chat))

        async def stream():
            try:
                while True:
                    item = await g.queue.get()
                    if item is None:
                        break
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            finally:
                if g.task and not g.task.done():
                    g.task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await g.task

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    def record_delivery(db, owner: Profile, conversation_id: str, body: DeliveryRequest, interrupted=False):
        owned_conversation(db, conversation_id, owner.id)
        row = db.scalar(select(Message).where(Message.conversation_id == conversation_id,
                                              Message.generation_id == body.generation_id,
                                              Message.role == "assistant"))
        if row is None or row.context_revision != owner.revision:
            raise HTTPException(409, "这段回复已经失效。")
        runtime = active.get(conversation_id)
        generated = runtime.text if runtime and runtime.id == body.generation_id else row.generated_text
        if not generated.startswith(body.displayed_text):
            raise HTTPException(422, "交付内容与已生成内容不匹配。")
        if len(body.displayed_text) >= len(row.delivered_text):
            row.delivered_text = body.displayed_text
        row.delivery_state = "interrupted" if interrupted else "delivered"
        db.commit()

    @app.post("/api/conversations/{conversation_id}/delivery")
    async def delivery(conversation_id: str, body: DeliveryRequest, request: Request):
        with sessions() as db:
            record_delivery(db, actor(request), conversation_id, body)
        return {"ok": True, "channel": "displayed_text"}

    @app.post("/api/conversations/{conversation_id}/interrupt")
    async def interrupt(conversation_id: str, body: DeliveryRequest, request: Request):
        owner = actor(request)
        with sessions() as db:
            record_delivery(db, owner, conversation_id, body, interrupted=True)
        runtime = active.get(conversation_id)
        if runtime and runtime.owner == owner.id and runtime.id == body.generation_id and runtime.task:
            runtime.task.cancel()
            await runtime.task
        return {"ok": True}

    @app.get("/api/memories")
    async def memories(request: Request):
        owner = actor(request)
        with sessions() as db:
            rows = db.scalars(select(Memory).where(Memory.owner_id == owner.id).order_by(Memory.created_at)).all()
            return [{"id": row.id, "text": row.text, "revision": row.revision, "created_at": row.created_at}
                    for row in rows]

    def invalidate_context(db, owner: str):
        # Edits start a fresh prompt context. Old visible chat remains readable but cannot reintroduce forgotten facts.
        cancel_owner(owner)
        db.get(Profile, owner).revision += 1

    @app.post("/api/memories")
    async def save_memory(body: MemoryRequest, request: Request):
        owner = actor(request)
        if not body.text.strip():
            raise HTTPException(422, "记忆不能为空。")
        with sessions() as db:
            rows = list(db.scalars(select(Memory.id).where(Memory.owner_id == owner.id)))
            if len(rows) >= 20:
                raise HTTPException(409, "体验版最多保存 20 条记忆，请先整理已有内容。")
            row = Memory(owner_id=owner.id, text=body.text.strip())
            db.add(row)
            invalidate_context(db, owner.id)
            db.commit()
            return {"id": row.id, "text": row.text, "revision": row.revision}

    @app.put("/api/memories/{memory_id}")
    async def correct_memory(memory_id: str, body: MemoryRequest, request: Request):
        owner = actor(request)
        with sessions() as db:
            row = db.scalar(select(Memory).where(Memory.id == memory_id, Memory.owner_id == owner.id))
            if row is None:
                raise HTTPException(404, "找不到这条记忆。")
            if not body.text.strip():
                raise HTTPException(422, "记忆不能为空。")
            row.text = body.text.strip()
            row.revision += 1
            invalidate_context(db, owner.id)
            db.commit()
            return {"id": row.id, "text": row.text, "revision": row.revision}

    @app.delete("/api/memories/{memory_id}")
    async def delete_memory(memory_id: str, request: Request):
        owner = actor(request)
        with sessions() as db:
            row = db.scalar(select(Memory).where(Memory.id == memory_id, Memory.owner_id == owner.id))
            if row is None:
                raise HTTPException(404, "找不到这条记忆。")
            db.delete(row)
            invalidate_context(db, owner.id)
            db.commit()
        return {"ok": True}

    @app.post("/api/audio/speech")
    async def speech(body: SpeechRequest, request: Request):
        actor(request)
        if not cfg.tts_ready and not local_tts:
            raise HTTPException(503, "尚未配置语音合成服务，可以选择系统朗读。")
        try:
            if cfg.tts_ready:
                audio, content_type = await synthesize(cfg, body.text)
            else:
                audio, content_type = await synthesize_local(body.text, language_for(body.text, body.language))
            return Response(audio, media_type=content_type)
        except (httpx.HTTPError, ValueError, OSError, TimeoutError):
            raise HTTPException(502, "语音合成未完成，请检查服务配置或稍后重试。") from None

    @app.post("/api/audio/transcribe")
    async def transcription(request: Request, audio: UploadFile = File(...), language: str = Form("auto")):
        actor(request)
        if not cfg.stt_ready:
            raise HTTPException(503, "尚未配置语音识别服务，请先使用文字输入。")
        content = await audio.read(cfg.max_audio_bytes + 1)
        await audio.close()
        if len(content) > cfg.max_audio_bytes:
            raise HTTPException(413, "录音过长，请缩短到一分钟以内。")
        if language not in ("auto", "zh-CN", "en-US"):
            raise HTTPException(422, "不支持的语言选项。")
        if not content:
            raise HTTPException(422, "录音为空。")
        try:
            text = await transcribe(cfg, content, audio.content_type or "audio/webm", language)
            return {"text": text}
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "语音识别未完成，请检查服务配置或使用文字输入。") from None

    @app.post("/api/conversations/{conversation_id}/voice-token")
    async def voice_token(conversation_id: str, request: Request):
        owner = actor(request)
        with sessions() as db:
            owned_conversation(db, conversation_id, owner.id)
        if not cfg.realtime_ready:
            raise HTTPException(503, "实时通话尚未配置完成。")
        if any(lease["owner"] == owner.id and lease["expires"] > time.monotonic() for lease in voice_leases.values()):
            raise HTTPException(409, "已有实时通话，请先结束后重试。")
        cancel_owner(owner.id)
        from datetime import timedelta
        from livekit import api
        room = f"qiban-{conversation_id}-{secrets.token_hex(4)}"
        voice_leases[conversation_id] = {"owner": owner.id, "revision": owner.revision,
                                        "room": room, "expires": time.monotonic() + 90}
        token = (api.AccessToken(cfg.livekit_api_key, cfg.livekit_api_secret)
                 .with_identity(owner.id).with_ttl(timedelta(minutes=10))
                 .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True,
                                            can_subscribe=True, can_publish_data=True)))
        return {"url": cfg.livekit_url, "token": token.to_jwt()}

    @app.post("/api/conversations/{conversation_id}/voice-end")
    async def voice_end(conversation_id: str, request: Request):
        owner = actor(request)
        with sessions() as db:
            owned_conversation(db, conversation_id, owner.id)
        voice_leases.pop(conversation_id, None)
        return {"ok": True}

    @app.get("/api/internal/voice/{room_name}")
    async def voice_context(room_name: str, request: Request):
        expected = f"Bearer {cfg.worker_secret}"
        if not cfg.worker_secret or not secrets.compare_digest(request.headers.get("authorization", ""), expected):
            raise HTTPException(401, "Worker authentication required")
        found = next(((cid, lease) for cid, lease in voice_leases.items()
                      if lease["room"] == room_name and lease["expires"] > time.monotonic()), None)
        if not found:
            raise HTTPException(409, "Voice lease expired")
        cid, lease = found
        with sessions() as db:
            owner = db.get(Profile, lease["owner"])
            if owner.revision != lease["revision"]:
                voice_leases.pop(cid, None)
                raise HTTPException(409, "Voice context changed")
            lease["expires"] = time.monotonic() + 90
            facts = list(db.scalars(select(Memory.text).where(Memory.owner_id == owner.id).limit(20)))
            return {"conversation_id": cid, "profile": profile_view(owner), "memories": facts}

    dist = ROOT / "dist"
    public = ROOT / "public"
    for prefix in ("models", "vendor"):
        directory = public / prefix
        directory.mkdir(parents=True, exist_ok=True)
        app.mount(f"/{prefix}", StaticFiles(directory=directory), name=prefix)
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    async def index():
        if not (dist / "index.html").is_file():
            return JSONResponse({"message": "Run npm run build, or open the Vite development server."})
        return FileResponse(dist / "index.html")

    return app
