import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.config import Settings
from backend.providers import ChatProvider


def settings(tmp_path, **overrides):
    return Settings(_env_file=None, database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
                    demo_chunk_delay=0, windows_tts_enabled=False, **overrides)


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def start(client):
    boot = client.post("/api/bootstrap")
    assert boot.status_code == 200
    return boot.json()["conversation_id"]


def send(client, conversation, text="你好", client_id=None):
    response = client.post(f"/api/conversations/{conversation}/turns",
                           json={"text": text, "client_turn_id": client_id or str(uuid4())})
    assert response.status_code == 200
    return events(response)


def test_delivery_is_explicit_and_prefix_checked(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        conversation = start(client)
        result = send(client, conversation)
        generation = result[0]["generation_id"]
        assert client.get(f"/api/conversations/{conversation}/messages").json()[0]["role"] == "user"
        body = {"generation_id": generation, "displayed_text": "a fabricated reply"}
        assert client.post(f"/api/conversations/{conversation}/delivery", json=body).status_code == 422
        prefix = result[-1]["payload"]["text"][:8]
        body["displayed_text"] = prefix
        assert client.post(f"/api/conversations/{conversation}/interrupt", json=body).status_code == 200
        history = client.get(f"/api/conversations/{conversation}/messages").json()
        assert history[-1]["text"] == prefix
        assert history[-1]["delivery_state"] == "interrupted"


def test_profiles_cannot_read_or_mutate_each_others_memory_or_chat(tmp_path):
    app = create_app(settings(tmp_path))
    with TestClient(app) as alice, TestClient(app) as bob:
        alice_conversation = start(alice)
        start(bob)
        memory = alice.post("/api/memories", json={"text": "只属于 Alice 的偏好"}).json()
        assert bob.get("/api/memories").json() == []
        assert bob.delete(f"/api/memories/{memory['id']}").status_code == 404
        assert bob.put(f"/api/memories/{memory['id']}", json={"text": "changed"}).status_code == 404
        assert bob.get(f"/api/conversations/{alice_conversation}/messages").status_code == 404
        assert bob.post(f"/api/conversations/{alice_conversation}/turns",
                        json={"text": "peek", "client_turn_id": str(uuid4())}).status_code == 404


def test_duplicate_turn_does_not_generate_again(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        conversation = start(client)
        client_id = str(uuid4())
        send(client, conversation, client_id=client_id)
        result = client.post(f"/api/conversations/{conversation}/turns",
                             json={"text": "你好", "client_turn_id": client_id})
        assert result.status_code == 409
        assert len(client.get(f"/api/conversations/{conversation}/messages").json()) == 1


def test_memory_correction_deletion_and_cross_conversation_recall(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        first = start(client)
        memory = client.post("/api/memories", json={"text": "喜欢乌龙茶"}).json()
        new = client.post("/api/conversations").json()["id"]
        assert new != first
        assert "乌龙茶" in send(client, new, "What do you remember?")[-1]["payload"]["text"]
        client.put(f"/api/memories/{memory['id']}", json={"text": "现在更喜欢红茶"})
        recalled = send(client, new, "你记得什么？")[-1]["payload"]["text"]
        assert "红茶" in recalled and "乌龙茶" not in recalled
        assert client.delete(f"/api/memories/{memory['id']}").status_code == 200
        assert client.get("/api/memories").json() == []
        assert "红茶" not in send(client, new, "你记得什么？")[-1]["payload"]["text"]


def test_untrusted_browser_origin_and_missing_session_are_rejected(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        assert client.get("/api/memories").status_code == 401
        assert client.post("/api/bootstrap", headers={"Origin": "https://untrusted.example"}).status_code == 403
        assert client.get("/api/health", headers={"Host": "rebind.example"}).status_code == 400
        start(client)
        assert client.post("/api/audio/speech", json={"text": "hello"}).status_code == 503


def test_history_list_is_private_and_retains_all_conversations(tmp_path):
    app = create_app(settings(tmp_path))
    with TestClient(app) as alice, TestClient(app) as bob:
        assert alice.get("/api/conversations").status_code == 401
        first = start(alice)
        other = start(bob)
        expected = {first}
        for _ in range(25):
            expected.add(alice.post("/api/conversations").json()["id"])
        history = alice.get("/api/conversations").json()
        assert {item["id"] for item in history} == expected
        assert all(item["title"] == "新的相伴" and item["preview"] == "" for item in history)
        assert [item["id"] for item in bob.get("/api/conversations").json()] == [other]
        assert bob.get(f"/api/conversations/{first}/messages").status_code == 404


def test_history_retains_persona_revision_after_switch_and_reload(tmp_path):
    cfg = settings(tmp_path)
    with TestClient(create_app(cfg)) as client:
        conversation = start(client)
        profile = client.post("/api/bootstrap").json()["profile"]
        first_revision = profile["revision"]
        first = send(client, conversation, "你是谁")
        client.post(f"/api/conversations/{conversation}/delivery",
                    json={"generation_id": first[0]["generation_id"], "displayed_text": first[-1]["payload"]["text"]})
        profile.update(name="言川", character_id="natori")
        changed = client.put("/api/profile", json=profile).json()
        second = send(client, conversation, "你是谁")
        client.post(f"/api/conversations/{conversation}/delivery",
                    json={"generation_id": second[0]["generation_id"], "displayed_text": second[-1]["payload"]["text"]})
        token = client.cookies.get("qiban_session")
    with TestClient(create_app(cfg)) as restored:
        restored.cookies.set("qiban_session", token)
        replies = [row for row in restored.get(f"/api/conversations/{conversation}/messages").json()
                   if row["role"] == "assistant"]
        assert len(replies) == 2
        assert "我是栖栖" in replies[0]["text"] and replies[0]["context_revision"] == first_revision
        assert "我是言川" in replies[1]["text"] and replies[1]["context_revision"] == changed["revision"]
        assert first_revision < changed["revision"]


def test_history_preview_only_contains_delivered_prefix(tmp_path):
    from sqlalchemy import update

    from backend.database import Message

    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        conversation = start(client)
        result = send(client, conversation, "今天想聊聊")
        # A user/assistant pair is inserted together and can share the same clock tick.
        with app.state.sessions() as db:
            db.execute(update(Message).where(Message.conversation_id == conversation)
                       .values(created_at="2026-09-14T00:00:00+00:00"))
            db.commit()
        assert client.get("/api/conversations").json()[0]["preview"] == "今天想聊聊"
        prefix = result[-1]["payload"]["text"][:8]
        client.post(f"/api/conversations/{conversation}/interrupt",
                    json={"generation_id": result[0]["generation_id"], "displayed_text": prefix})
        summary = client.get("/api/conversations").json()[0]
        assert summary["title"] == "今天想聊聊"
        assert summary["preview"] == prefix
        history = client.get(f"/api/conversations/{conversation}/messages").json()
        assert [row["role"] for row in history] == ["user", "assistant"]


def test_old_history_can_be_reopened_continued_and_restored_after_restart(tmp_path):
    prompts = []

    class Provider:
        async def stream(self, prompt, **_kwargs):
            prompts.append(prompt)
            yield "我记得这次聊天。"

    cfg = settings(tmp_path)
    with TestClient(create_app(cfg, Provider())) as client:
        first = start(client)
        result = send(client, first, "第一段，周末去看海")
        client.post(f"/api/conversations/{first}/delivery",
                    json={"generation_id": result[0]["generation_id"], "displayed_text": "我记得这次聊天。"})
        second = client.post("/api/conversations").json()["id"]
        assert [row["id"] for row in client.get("/api/conversations").json()] == [second, first]
        send(client, second, "第二段，讨论晚餐")
        assert client.get(f"/api/conversations/{first}/messages").json()[-1]["text"] == "我记得这次聊天。"
        send(client, first, "接着刚才的话题")
        assert [row["id"] for row in client.get("/api/conversations").json()] == [first, second]
        contents = [item["content"] for item in prompts[-1]]
        assert "第一段，周末去看海" in contents and "我记得这次聊天。" in contents
        assert "第二段，讨论晚餐" not in contents
        token = client.cookies.get("qiban_session")
    with TestClient(create_app(cfg, Provider())) as restored:
        restored.cookies.set("qiban_session", token)
        assert {item["id"] for item in restored.get("/api/conversations").json()} == {first, second}
        assert restored.get(f"/api/conversations/{first}/messages").json()[-1]["text"] == "接着刚才的话题"


@pytest.mark.asyncio
async def test_memory_edit_cancels_inflight_generation_and_rejects_late_delivery(tmp_path):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class SlowProvider:
        async def stream(self, *_args, **_kwargs):
            try:
                yield "旧偏好"
                started.set()
                await asyncio.sleep(60)
                yield "不应出现"
            finally:
                cancelled.set()

    app = create_app(settings(tmp_path), SlowProvider())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://testserver") as client:
        conversation = (await client.post("/api/bootstrap")).json()["conversation_id"]
        memory = (await client.post("/api/memories", json={"text": "旧偏好"})).json()
        task = asyncio.create_task(client.post(f"/api/conversations/{conversation}/turns",
                                               json={"text": "记得什么", "client_turn_id": str(uuid4())}))
        await asyncio.wait_for(started.wait(), 3)
        assert (await client.delete(f"/api/memories/{memory['id']}")).status_code == 200
        result = events(await asyncio.wait_for(task, 3))
        assert cancelled.is_set()
        assert "不应出现" not in json.dumps(result, ensure_ascii=False)
        late = await client.post(f"/api/conversations/{conversation}/delivery",
                                 json={"generation_id": result[0]["generation_id"], "displayed_text": "旧偏好"})
        assert late.status_code == 409


@pytest.mark.asyncio
async def test_gateway_uses_supplied_contract_and_never_silently_falls_back(tmp_path):
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        assert str(request.url) == "https://gateway.example/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-only-key"
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"你好"}}]}\n\ndata: [DONE]\n\n')

    cfg = settings(tmp_path, chat_base_url="https://gateway.example/v1", chat_model="gpt-5.6-sol",
                   chat_api_key="test-only-key")
    provider = ChatProvider(cfg, httpx.MockTransport(handler))
    result = [part async for part in provider.stream([{"role": "user", "content": "你好"}],
                                                     name="栖栖", language="zh-CN", memories=[])]
    assert result == ["你好"]
    assert captured[0]["model"] == "gpt-5.6-sol"
    assert "temperature" not in captured[0] and "max_tokens" not in captured[0]
    failed = ChatProvider(cfg, httpx.MockTransport(lambda _: httpx.Response(401)))
    with pytest.raises(httpx.HTTPStatusError):
        _ = [part async for part in failed.stream([{"role": "user", "content": "你好"}],
                                                  name="栖栖", language="zh-CN", memories=[])]


def test_gateway_error_is_bounded_without_credentials_in_client_events(tmp_path):
    cfg = settings(tmp_path, chat_base_url="https://gateway.example/v1", chat_model="configured",
                   chat_api_key="private-test-secret")
    provider = ChatProvider(cfg, httpx.MockTransport(lambda _: httpx.Response(401, text="private-test-secret")))
    with TestClient(create_app(cfg, provider)) as client:
        result = send(client, start(client))
        assert result[-1]["type"] == "assistant.error"
        assert "private-test-secret" not in json.dumps(result)


def test_blank_profile_and_memories_are_rejected(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        start(client)
        assert client.post("/api/memories", json={"text": "  "}).status_code == 422
        assert client.put("/api/profile", json={"name": "  ", "persona": "A sufficiently long style"}).status_code == 422


def test_voice_lease_is_scoped_authenticated_and_invalidated_by_memory_edits(tmp_path):
    import jwt

    cfg = settings(tmp_path, chat_base_url="https://example.test/v1", chat_model="test", chat_api_key="test",
                   stt_base_url="https://example.test/v1", stt_model="test",
                   tts_base_url="https://example.test/v1", tts_model="test", livekit_url="ws://localhost:7880",
                   livekit_api_key="local-test", livekit_api_secret="x" * 32, worker_secret="worker-test-secret")
    app = create_app(cfg)
    with TestClient(app) as alice, TestClient(app) as bob:
        conversation = start(alice)
        start(bob)
        route = f"/api/conversations/{conversation}"
        assert bob.post(f"{route}/voice-token").status_code == 404
        response = alice.post(f"{route}/voice-token")
        assert response.status_code == 200
        token = jwt.decode(response.json()["token"], cfg.livekit_api_secret, algorithms=["HS256"])
        room = token["video"]["room"]
        assert room.startswith(f"qiban-{conversation}-")
        assert token["video"]["roomJoin"] is True
        worker_route = f"/api/internal/voice/{room}"
        assert alice.get(worker_route).status_code == 401
        headers = {"Authorization": f"Bearer {cfg.worker_secret}"}
        assert alice.get(worker_route, headers=headers).json()["conversation_id"] == conversation
        assert alice.post(f"{route}/voice-token").status_code == 409
        assert alice.post(f"{route}/turns", json={"text": "hi", "client_turn_id": str(uuid4())}).status_code == 409
        assert bob.post(f"{route}/voice-end").status_code == 404
        assert alice.post("/api/memories", json={"text": "Call me Alex"}).status_code == 200
        assert alice.get(worker_route, headers=headers).status_code == 409
        next_token = alice.post(f"{route}/voice-token").json()["token"]
        next_room = jwt.decode(next_token, cfg.livekit_api_secret, algorithms=["HS256"])["video"]["room"]
        assert room != next_room
        assert alice.post(f"{route}/voice-end").status_code == 200
        assert alice.get(f"/api/internal/voice/{next_room}", headers=headers).status_code == 409


@pytest.mark.asyncio
async def test_truncated_gateway_stream_is_not_reported_as_completed(tmp_path):
    cfg = settings(tmp_path, chat_base_url="https://example.test/v1", chat_model="test", chat_api_key="test")
    provider = ChatProvider(cfg, httpx.MockTransport(lambda _: httpx.Response(
        200, text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')))
    parts = []
    with pytest.raises(ValueError, match="without completion"):
        async for part in provider.stream([], name="test", language="en-US", memories=[]):
            parts.append(part)
    assert parts == ["partial"]
