import hashlib
import secrets
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid() -> str:
    return str(uuid4())


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_hash: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(40), default="栖栖")
    user_name: Mapped[str] = mapped_column(String(40), default="")
    persona: Mapped[str] = mapped_column(Text, default="温柔、坦诚，有一点幽默。先听懂感受，再决定是否给建议。回答简短自然，不机械追问，不一味附和。")
    language: Mapped[str] = mapped_column(String(12), default="auto")
    character_id: Mapped[str] = mapped_column(String(32), default="hiyori", server_default="hiyori")
    revision: Mapped[int] = mapped_column(default=1)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    title: Mapped[str] = mapped_column(String(90), default="新的相伴")
    created_at: Mapped[str] = mapped_column(String(40), default=timestamp)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "client_turn_id", "role"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    client_turn_id: Mapped[str] = mapped_column(String(70))
    role: Mapped[str] = mapped_column(String(20))
    generated_text: Mapped[str] = mapped_column(Text, default="")
    delivered_text: Mapped[str] = mapped_column(Text, default="")
    generation_id: Mapped[str] = mapped_column(String(36), default="")
    context_revision: Mapped[int] = mapped_column(default=1)
    delivery_state: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[str] = mapped_column(String(40), default=timestamp)


class Memory(Base):
    __tablename__ = "memories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[str] = mapped_column(String(40), default=timestamp)


def make_database(url: str):
    options = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=options, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    # Additive migration for existing 0.1/0.2 databases; keep every profile and message intact.
    if "character_id" not in {column["name"] for column in inspect(engine).get_columns("profiles")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE profiles ADD COLUMN character_id VARCHAR(32) NOT NULL DEFAULT 'hiyori'"))
    return engine, sessionmaker(engine, expire_on_commit=False)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)
