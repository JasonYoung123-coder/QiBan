import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.config import Settings
from backend.connection_settings import ConnectionStore, ConnectionsUpdate, SettingsConflict
from backend.providers import ChatProvider


def config(tmp_path, **kwargs):
    return Settings(_env_file=None, database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
                    windows_tts_enabled=False, **kwargs)


def editable(public):
    data = json.loads(json.dumps(public))
    for group in [*data['chats'].values(), data['voice']]:
        for name in list(group):
            if name.endswith('_set'):
                group[name[:-4]] = None
                del group[name]
    return data


def test_persistence_profile_isolation_and_explicit_clear(tmp_path):
    cfg = config(tmp_path, chat_base_url='https://gateway.example/v1', chat_model='existing', chat_api_key='legacy')
    path = tmp_path / 'connections.json'
    store = ConnectionStore(cfg, path)
    data = editable(store.public())
    data['chat_provider'] = 'anthropic'
    data['chats']['anthropic'].update(model='chosen-model', api_key='new-secret')
    store.save(ConnectionsUpdate.model_validate(data))
    loaded = ConnectionStore(cfg, path)
    assert loaded.apply(cfg).chat_api_key == 'new-secret'
    assert loaded.document['chats']['openai']['api_key'] == 'legacy'
    assert 'new-secret' not in json.dumps(loaded.public())
    data = editable(loaded.public())
    data['chats']['anthropic']['api_key'] = ''
    loaded.save(ConnectionsUpdate.model_validate(data))
    assert ConnectionStore(cfg, path).apply(cfg).chat_api_key == ''
    with pytest.raises(SettingsConflict):
        loaded.save(ConnectionsUpdate.model_validate(data))


def test_endpoint_change_requires_explicit_key_choice(tmp_path):
    cfg = config(tmp_path, chat_base_url='https://a.example/v1', chat_api_key='secret')
    store = ConnectionStore(cfg)
    data = editable(store.public())
    data['chats']['openai']['base_url'] = 'https://b.example/v1'
    with pytest.raises(ValueError, match='密钥'):
        store.preview(ConnectionsUpdate.model_validate(data), cfg)
    data['chats']['openai']['api_key'] = ''
    assert store.preview(ConnectionsUpdate.model_validate(data), cfg).chat_api_key == ''
    assert store.apply(cfg).chat_base_url == 'https://a.example/v1'


def test_settings_api_masks_keys_validates_origins_and_applies_immediately(tmp_path):
    cfg = config(tmp_path)
    store = ConnectionStore(cfg, tmp_path / 'connections.json')
    app = create_app(cfg, settings_store=store)
    with TestClient(app) as client:
        assert client.get('/api/settings').status_code == 401
        client.post('/api/bootstrap')
        data = editable(client.get('/api/settings').json()['settings'])
        data['chat_provider'] = 'anthropic'
        data['chats']['anthropic'].update(model='test', api_key='secret-that-must-not-leak')
        assert client.put('/api/settings', json=data, headers={'Origin':'https://evil.example'}).status_code == 403
        result = client.put('/api/settings', json=data)
        assert result.status_code == 200
        assert 'secret-that-must-not-leak' not in result.text
        assert result.json()['capabilities']['chat'] == 'connected'
        assert app.state.settings.chat_provider == 'anthropic'
        assert app.state.settings.chat_api_key == 'secret-that-must-not-leak'
        assert client.put('/api/settings', json=data).status_code == 409
        data['chats']['anthropic']['api_key'] = {'secret-that-must-not-leak':'invalid'}
        invalid = client.put('/api/settings', json=data)
        assert invalid.status_code == 422
        assert 'secret-that-must-not-leak' not in invalid.text
        assert result.headers['cache-control'] == 'no-store'


def test_connection_test_does_not_save_or_send_history(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    path = tmp_path / 'connections.json'
    app = create_app(cfg, settings_store=ConnectionStore(cfg, path))
    seen = []

    async def stream(self, messages, **kwargs):
        seen.append((self.settings.chat_provider, messages, kwargs))
        yield 'OK'

    monkeypatch.setattr(ChatProvider, 'stream', stream)
    with TestClient(app) as client:
        client.post('/api/bootstrap')
        data = editable(client.get('/api/settings').json()['settings'])
        data['chat_provider'] = 'responses'
        data['chats']['responses'].update(model='test', api_key='fake')
        assert client.post('/api/settings/test', json=data).status_code == 200
        assert not path.exists()
        assert app.state.settings.chat_provider == 'openai'
        assert seen == [('responses', [{'role':'user','content':'Reply with OK.'}],
                         {'name':'connection-test','language':'en-US','memories':[]})]


PROTOCOLS = {
    'openai': ('chat/completions', [{'choices':[{'delta':{'content':'你好 Hi'}}]}, '[DONE]']),
    'responses': ('responses', [{'type':'response.output_text.delta','delta':'你好 Hi'}, {'type':'response.completed'}]),
    'anthropic': ('messages', [{'type':'ping'}, {'type':'content_block_delta','delta':{'type':'text_delta','text':'你好 Hi'}}, {'type':'message_stop'}]),
}


class Fragmented(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data
        self.closed = False

    async def __aiter__(self):
        for byte in self.data:
            yield bytes([byte])

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize('provider', list(PROTOCOLS))
@pytest.mark.asyncio
async def test_protocol_bilingual_sse_auth_and_system(tmp_path, provider):
    suffix, events = PROTOCOLS[provider]
    payload = ': keepalive\r\n\r\n' + ''.join('data: ' + (event if isinstance(event,str) else json.dumps(event,ensure_ascii=False)) + '\r\n\r\n' for event in events)
    stream = Fragmented(payload.encode())
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, stream=stream)

    cfg = config(tmp_path, chat_provider=provider, chat_base_url=f'https://service.example/v1/{suffix}',
                 chat_model='chosen-model', chat_api_key='test-key')
    model = ChatProvider(cfg, httpx.MockTransport(handle))
    prompt = [{'role':'system','content':'warm persona'}, {'role':'user','content':'你好'}]
    assert ''.join([text async for text in model.stream(prompt,name='test',language='auto',memories=[])]) == '你好 Hi'
    request = seen[0]
    assert request.url.path == f'/v1/{suffix}'
    body = json.loads(request.content)
    assert body['model'] == 'chosen-model'
    if provider == 'anthropic':
        assert request.headers['x-api-key'] == 'test-key'
        assert request.headers['anthropic-version'] == '2023-06-01'
        assert 'authorization' not in request.headers
        assert body['max_tokens'] == 4096 and body['system'] == 'warm persona'
        assert body['messages'] == prompt[1:]
    elif provider == 'responses':
        assert body['input'] == prompt[1:] and body['instructions'] == 'warm persona'
        assert body['store'] is False
    else:
        assert body['messages'] == prompt
        assert request.headers['authorization'] == 'Bearer test-key'
    assert stream.closed


@pytest.mark.parametrize('provider', list(PROTOCOLS))
@pytest.mark.parametrize('data', ['', 'data: {"type":"error","error":{"message":"fake-secret"}}\n\n'])
@pytest.mark.asyncio
async def test_truncated_or_failed_stream_is_not_success(tmp_path, provider, data):
    cfg = config(tmp_path, chat_provider=provider, chat_base_url='https://service.example/v1',chat_model='test',chat_api_key='fake')
    model = ChatProvider(cfg, httpx.MockTransport(lambda _: httpx.Response(200,text=data)))
    with pytest.raises(ValueError):
        _ = [text async for text in model.stream([{'role':'user','content':'hi'}],name='test',language='en',memories=[])]


@pytest.mark.asyncio
async def test_save_cancels_current_generation(tmp_path):
    from uuid import uuid4
    started, stopped = asyncio.Event(), asyncio.Event()

    class Slow:
        async def stream(self, *args, **kwargs):
            try:
                yield 'prefix'
                started.set()
                await asyncio.sleep(60)
            finally:
                stopped.set()

    app = create_app(config(tmp_path), provider=Slow())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
        boot = (await client.post('/api/bootstrap')).json()
        task = asyncio.create_task(client.post(f"/api/conversations/{boot['conversation_id']}/turns",
                                              json={'text':'hi','client_turn_id':str(uuid4())}))
        await asyncio.wait_for(started.wait(),2)
        data = editable((await client.get('/api/settings')).json()['settings'])
        assert (await client.put('/api/settings',json=data)).status_code == 200
        await asyncio.wait_for(stopped.wait(),2)
        await asyncio.wait_for(task,2)


@pytest.mark.parametrize('provider', list(PROTOCOLS))
@pytest.mark.asyncio
async def test_voice_uses_selected_provider(tmp_path, provider):
    pytest.importorskip('livekit.agents')
    from livekit.agents import llm
    from backend.voice_llm import CompanionLLM
    _, events = PROTOCOLS[provider]
    data = ''.join('data: '+(item if isinstance(item,str) else json.dumps(item))+'\n\n' for item in events)
    cfg = config(tmp_path, chat_provider=provider, chat_base_url='https://test.example/v1',chat_model='test',chat_api_key='fake')
    model = CompanionLLM(cfg,httpx.MockTransport(lambda _:httpx.Response(200,text=data)))
    context = llm.ChatContext()
    context.add_message(role='system',content='persona')
    context.add_message(role='user',content='hello')
    assert (await model.chat(chat_ctx=context).collect()).text == '你好 Hi'
    await model.aclose()
