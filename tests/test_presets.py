import sqlite3

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from backend.api import create_app
from backend.config import Settings
from backend.connection_settings import ConnectionStore
from backend.database import Profile, make_database


def test_old_database_additive_character_migration(tmp_path):
    path = tmp_path / 'old.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE profiles (id VARCHAR(36) PRIMARY KEY, session_hash VARCHAR(64), '
                   'name VARCHAR(40), user_name VARCHAR(40), persona TEXT, language VARCHAR(12), revision INTEGER)')
        db.execute("INSERT INTO profiles VALUES ('old', 'hash', 'Existing', 'User', 'old persona', 'auto', 4)")
    url = f"sqlite:///{path.as_posix()}"
    engine, sessions = make_database(url)
    with sessions() as db:
        row = db.scalar(select(Profile))
        assert (row.name, row.persona, row.character_id, row.revision) == ('Existing','old persona','hiyori',4)
    assert 'character_id' in {column['name'] for column in inspect(engine).get_columns('profiles')}
    engine.dispose()
    engine, _ = make_database(url)  # Repeated startup must not add the same column twice.
    engine.dispose()


def test_character_save_restart_and_validation(tmp_path):
    cfg = Settings(_env_file=None, database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}", windows_tts_enabled=False)
    with TestClient(create_app(cfg)) as client:
        profile = client.post('/api/bootstrap').json()['profile']
        assert profile['character_id'] == 'hiyori'
        profile.update(character_id='natori', name='言川', persona='沉稳温和的男性陪伴伙伴，表达自然简短。')
        result = client.put('/api/profile',json=profile)
        assert result.status_code == 200 and result.json()['character_id'] == 'natori'
        cookie = client.cookies.get('qiban_session')
        profile['character_id'] = '../../not-a-model'
        assert client.put('/api/profile',json=profile).status_code == 422
    with TestClient(create_app(cfg)) as client:
        client.cookies.set('qiban_session',cookie)
        restored = client.post('/api/bootstrap').json()['profile']
        assert restored['character_id'] == 'natori' and restored['name'] == '言川'


def test_deepseek_defaults_only_for_unconfigured_installations():
    empty = Settings(_env_file=None)
    cfg = ConnectionStore(empty).apply(empty)
    assert cfg.chat_base_url == 'https://api.deepseek.com' and cfg.chat_model == 'deepseek-flash'
    assert not cfg.chat_ready
    existing = Settings(_env_file=None,chat_base_url='https://mine.example/v1',chat_model='mine',chat_api_key='fake')
    restored = ConnectionStore(existing).apply(existing)
    assert (restored.chat_base_url,restored.chat_model,restored.chat_api_key) == ('https://mine.example/v1','mine','fake')
