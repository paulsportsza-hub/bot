"""Async SQLAlchemy models & helpers for MzansiEdge."""

from __future__ import annotations

import datetime as dt
from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, Integer, String, Text,
    func, select, delete,
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
    risk_profile: Mapped[str | None] = mapped_column(String(32))
    notification_hour: Mapped[int | None] = mapped_column(Integer)
    onboarding_done: Mapped[bool] = mapped_column(Boolean, default=False)
    experience_level: Mapped[str | None] = mapped_column(String(32))  # experienced/casual/newbie
    education_stage: Mapped[int] = mapped_column(Integer, default=0)  # newbie lesson progress
    archetype: Mapped[str | None] = mapped_column(String(50))  # eager_bettor/casual_fan/complete_newbie
    engagement_score: Mapped[float] = mapped_column(Float, default=5.0)
    source: Mapped[str | None] = mapped_column(String(100))  # organic, fb_ad_123, etc.
    fb_click_id: Mapped[str | None] = mapped_column(String(255))
    fb_ad_id: Mapped[str | None] = mapped_column(String(255))


class UserSportPref(Base):
    __tablename__ = "user_sport_prefs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    sport_key: Mapped[str] = mapped_column(String(64))
    league: Mapped[str | None] = mapped_column(String(128))
    team_name: Mapped[str | None] = mapped_column(String(128))


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
    # SQLite column migration for existing databases
    await _migrate_columns()


async def _migrate_columns() -> None:
    """Add new columns to existing SQLite tables if missing."""
    import aiosqlite
    db_url = config.DATABASE_URL
    if "sqlite" not in db_url:
        return
    # Extract path from aiosqlite URL: "sqlite+aiosqlite:///data/mzansiedge.db"
    db_path = db_url.split("///", 1)[-1] if "///" in db_url else None
    if not db_path or db_path == ":memory:":
        return
    try:
        async with aiosqlite.connect(db_path) as conn:
            for col, default in [
                ("experience_level", "NULL"),
                ("education_stage", "0"),
                ("archetype", "NULL"),
                ("engagement_score", "5.0"),
                ("source", "NULL"),
                ("fb_click_id", "NULL"),
                ("fb_ad_id", "NULL"),
            ]:
                try:
                    await conn.execute(
                        f"ALTER TABLE users ADD COLUMN {col} DEFAULT {default}"
                    )
                except Exception:
                    pass  # Column already exists
            await conn.commit()
    except Exception:
        pass  # DB file may not exist yet


async def upsert_user(user_id: int, username: str | None, first_name: str | None) -> User:
    async with async_session() as s:
        existing = await s.get(User, user_id)
        if existing:
            existing.username = username
            existing.first_name = first_name
            existing.is_active = True
        else:
            existing = User(id=user_id, username=username, first_name=first_name)
            s.add(existing)
        await s.commit()
        await s.refresh(existing)
        return existing


async def get_user(user_id: int) -> User | None:
    async with async_session() as s:
        return await s.get(User, user_id)


async def update_user_risk(user_id: int, risk_profile: str) -> None:
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.risk_profile = risk_profile
            await s.commit()


async def update_user_notification_hour(user_id: int, hour: int) -> None:
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.notification_hour = hour
            await s.commit()


async def update_user_experience(user_id: int, experience_level: str) -> None:
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.experience_level = experience_level
            await s.commit()


async def set_onboarding_done(user_id: int) -> None:
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.onboarding_done = True
            await s.commit()


async def save_sport_pref(
    user_id: int,
    sport_key: str,
    league: str | None = None,
    team_name: str | None = None,
) -> UserSportPref:
    async with async_session() as s:
        pref = UserSportPref(
            user_id=user_id, sport_key=sport_key,
            league=league, team_name=team_name,
        )
        s.add(pref)
        await s.commit()
        await s.refresh(pref)
        return pref


async def get_user_sport_prefs(user_id: int) -> list[UserSportPref]:
    async with async_session() as s:
        result = await s.execute(
            select(UserSportPref).where(UserSportPref.user_id == user_id)
        )
        return list(result.scalars().all())


async def clear_user_sport_prefs(user_id: int) -> None:
    async with async_session() as s:
        await s.execute(
            delete(UserSportPref).where(UserSportPref.user_id == user_id)
        )
        await s.commit()


async def update_pref_team(pref_id: int, team_name: str) -> None:
    async with async_session() as s:
        pref = await s.get(UserSportPref, pref_id)
        if pref:
            pref.team_name = team_name
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


async def save_bet(user_id: int, tip_id: int, stake: float) -> Bet:
    async with async_session() as s:
        bet = Bet(user_id=user_id, tip_id=tip_id, stake=stake)
        s.add(bet)
        await s.commit()
        await s.refresh(bet)
        return bet


async def reset_user_profile(user_id: int) -> None:
    """Wipe all user preferences but keep account + history."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.onboarding_done = False
            user.risk_profile = None
            user.notification_hour = None
            user.experience_level = None
            user.education_stage = 0
            user.archetype = None
            user.engagement_score = 5.0
            await s.commit()
    await clear_user_sport_prefs(user_id)


async def update_user_archetype(
    user_id: int, archetype: str, engagement_score: float,
) -> None:
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.archetype = archetype
            user.engagement_score = engagement_score
            await s.commit()


async def get_user_count() -> int:
    async with async_session() as s:
        result = await s.execute(select(func.count(User.id)))
        return result.scalar_one()
