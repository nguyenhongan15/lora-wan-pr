"""
database.py — Async SQLAlchemy engine + session factory.

DATABASE_URL được đọc từ config.py (pydantic-settings).
Tuân thủ 12-Factor App Factor 3 (Config): cấu hình qua biến môi trường.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=(settings.app_env == "development"),
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency — yield async session."""
    async with AsyncSessionLocal() as session:
        yield session
