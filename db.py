"""Async SQLAlchemy models & helpers for PaulSportSA."""

from __future__ import annotations

import datetime as dt
from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, Integer, String, Text,
    func, select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

import config

engine = create_async_engine(config.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user id
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    joined_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Tip(Base):
    __tablename__ = "tips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sport: Mapped[str] = mapped_column(String(32))
    match: Mapped[str] = mapped_column(String(256))
    prediction: Mapped[str] = mapped_column(Text)
    odds: Mapped[float | None] = mapped_column(Float)
    result: Mapped[str | None] = mapped_column(String(16))  # win / loss / pending
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Bet(Base):
    __tablename__ = "bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    tip_id: Mapped[int] = mapped_column(Integer)
    stake: Mapped[float] = mapped_column(Float)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── Helper functions ──────────────────────────────────────

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def upsert_user(user_id: int, username: str | None, first_name: str | None) -> None:
    async with async_session() as s:
        existing = await s.get(User, user_id)
        if existing:
            existing.username = username
            existing.first_name = first_name
            existing.is_active = True
        else:
            s.add(User(id=user_id, username=username, first_name=first_name))
        await s.commit()


async def save_tip(sport: str, match: str, prediction: str, odds: float | None = None) -> Tip:
    async with async_session() as s:
        tip = Tip(sport=sport, match=match, prediction=prediction, odds=odds)
        s.add(tip)
        await s.commit()
        await s.refresh(tip)
        return tip


async def get_recent_tips(limit: int = 10) -> list[Tip]:
    async with async_session() as s:
        result = await s.execute(
            select(Tip).order_by(Tip.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


async def get_user_count() -> int:
    async with async_session() as s:
        result = await s.execute(select(func.count(User.id)))
        return result.scalar_one()
