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
    notification_prefs: Mapped[str | None] = mapped_column(Text)  # JSON notification preferences
    bankroll: Mapped[float | None] = mapped_column(Float)  # weekly bankroll in ZAR
    source: Mapped[str | None] = mapped_column(String(100))  # organic, fb_ad_123, etc.
    fb_click_id: Mapped[str | None] = mapped_column(String(255))
    fb_ad_id: Mapped[str | None] = mapped_column(String(255))
    # WhatsApp readiness
    whatsapp_phone: Mapped[str | None] = mapped_column(String(32))  # e.g. "+27821234567"
    preferred_platform: Mapped[str | None] = mapped_column(String(16))  # "telegram" | "whatsapp"
    # UX flags
    edge_tooltip_shown: Mapped[bool] = mapped_column(Boolean, default=False)
    # Paystack subscription
    email: Mapped[str | None] = mapped_column(String(255))  # for Paystack
    subscription_status: Mapped[str | None] = mapped_column(String(32))  # "active" | "cancelled" | None
    subscription_code: Mapped[str | None] = mapped_column(String(128))  # Paystack subscription code
    plan_code: Mapped[str | None] = mapped_column(String(128))  # Paystack plan code
    subscription_started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


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


class GameSubscription(Base):
    __tablename__ = "game_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    event_id: Mapped[str] = mapped_column(String(128))
    sport_key: Mapped[str | None] = mapped_column(String(64))
    home_team: Mapped[str | None] = mapped_column(String(128))
    away_team: Mapped[str | None] = mapped_column(String(128))
    commence_time: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
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
                ("notification_prefs", "NULL"),
                ("bankroll", "NULL"),
                ("source", "NULL"),
                ("fb_click_id", "NULL"),
                ("fb_ad_id", "NULL"),
                ("whatsapp_phone", "NULL"),
                ("preferred_platform", "'telegram'"),
                ("edge_tooltip_shown", "0"),
                ("email", "NULL"),
                ("subscription_status", "NULL"),
                ("subscription_code", "NULL"),
                ("plan_code", "NULL"),
                ("subscription_started_at", "NULL"),
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


async def set_edge_tooltip_shown(user_id: int) -> None:
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.edge_tooltip_shown = True
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


async def clear_user_league_teams(user_id: int, sport_key: str, league_key: str) -> None:
    """Delete team prefs for a specific league while keeping the league pref itself."""
    async with async_session() as s:
        await s.execute(
            delete(UserSportPref).where(
                UserSportPref.user_id == user_id,
                UserSportPref.sport_key == sport_key,
                UserSportPref.league == league_key,
                UserSportPref.team_name != None,  # noqa: E711
            )
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
            user.bankroll = None
            user.whatsapp_phone = None
            user.preferred_platform = None
            await s.commit()
    await clear_user_sport_prefs(user_id)


async def update_user_bankroll(user_id: int, bankroll: float | None) -> None:
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.bankroll = bankroll
            await s.commit()


async def update_user_whatsapp(
    user_id: int, phone: str | None, platform: str = "whatsapp",
) -> None:
    """Set WhatsApp phone number and preferred platform."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.whatsapp_phone = phone
            user.preferred_platform = platform
            await s.commit()


async def update_user_archetype(
    user_id: int, archetype: str, engagement_score: float,
) -> None:
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.archetype = archetype
            user.engagement_score = engagement_score
            await s.commit()


def get_notification_prefs(user: User | None) -> dict:
    """Parse JSON notification prefs with defaults."""
    import json
    default = {
        "daily_picks": True,
        "game_day_alerts": True,
        "weekly_recap": True,
        "edu_tips": True,
        "market_movers": False,
        "bankroll_updates": True,
    }
    if not user:
        return default
    try:
        prefs = json.loads(user.notification_prefs or "{}")
        return {**default, **prefs}
    except Exception:
        return default


async def update_notification_prefs(user_id: int, prefs: dict) -> None:
    """Save notification preferences as JSON."""
    import json
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.notification_prefs = json.dumps(prefs)
            await s.commit()


async def subscribe_to_game(
    user_id: int, event_id: str,
    sport_key: str | None = None,
    home_team: str | None = None,
    away_team: str | None = None,
    commence_time: str | None = None,
) -> GameSubscription:
    """Subscribe a user to live score updates for a game."""
    async with async_session() as s:
        # Check for existing subscription
        result = await s.execute(
            select(GameSubscription).where(
                GameSubscription.user_id == user_id,
                GameSubscription.event_id == event_id,
                GameSubscription.is_active == True,  # noqa: E712
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        sub = GameSubscription(
            user_id=user_id, event_id=event_id,
            sport_key=sport_key, home_team=home_team,
            away_team=away_team, commence_time=commence_time,
        )
        s.add(sub)
        await s.commit()
        await s.refresh(sub)
        return sub


async def unsubscribe_from_game(user_id: int, event_id: str) -> None:
    """Unsubscribe a user from a game."""
    async with async_session() as s:
        result = await s.execute(
            select(GameSubscription).where(
                GameSubscription.user_id == user_id,
                GameSubscription.event_id == event_id,
                GameSubscription.is_active == True,  # noqa: E712
            )
        )
        for sub in result.scalars().all():
            sub.is_active = False
        await s.commit()


async def get_user_subscriptions(user_id: int) -> list[GameSubscription]:
    """Get all active subscriptions for a user."""
    async with async_session() as s:
        result = await s.execute(
            select(GameSubscription).where(
                GameSubscription.user_id == user_id,
                GameSubscription.is_active == True,  # noqa: E712
            )
        )
        return list(result.scalars().all())


async def get_subscribers_for_event(event_id: str) -> list[GameSubscription]:
    """Get all active subscribers for an event."""
    async with async_session() as s:
        result = await s.execute(
            select(GameSubscription).where(
                GameSubscription.event_id == event_id,
                GameSubscription.is_active == True,  # noqa: E712
            )
        )
        return list(result.scalars().all())


async def deactivate_subscriptions_for_event(event_id: str) -> None:
    """Deactivate all subscriptions for a completed event."""
    async with async_session() as s:
        result = await s.execute(
            select(GameSubscription).where(
                GameSubscription.event_id == event_id,
                GameSubscription.is_active == True,  # noqa: E712
            )
        )
        for sub in result.scalars().all():
            sub.is_active = False
        await s.commit()


async def get_users_for_notification(hour: int) -> list[User]:
    """Get onboarded users whose notification_hour matches and who want daily_picks."""
    import json
    async with async_session() as s:
        result = await s.execute(
            select(User).where(
                User.onboarding_done == True,  # noqa: E712
                User.notification_hour == hour,
                User.is_active == True,  # noqa: E712
            )
        )
        users = list(result.scalars().all())
        # Filter to users who have daily_picks enabled
        filtered = []
        for u in users:
            prefs = get_notification_prefs(u)
            if prefs.get("daily_picks", True):
                filtered.append(u)
        return filtered


async def update_user_email(user_id: int, email: str) -> None:
    """Store user's email for Paystack."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.email = email
            await s.commit()


async def activate_subscription(
    user_id: int, subscription_code: str, plan_code: str,
) -> None:
    """Mark user as subscribed after successful Paystack payment."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.subscription_status = "active"
            user.subscription_code = subscription_code
            user.plan_code = plan_code
            user.subscription_started_at = dt.datetime.now(dt.timezone.utc)
            await s.commit()


async def deactivate_subscription(user_id: int) -> None:
    """Deactivate user subscription (cancelled or expired)."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.subscription_status = "cancelled"
            await s.commit()


async def get_user_by_email(email: str) -> User | None:
    """Find a user by email (for webhook resolution)."""
    async with async_session() as s:
        result = await s.execute(select(User).where(User.email == email))
        return result.scalars().first()


def is_premium(user: User | None) -> bool:
    """Check if a user has an active premium subscription."""
    if not user:
        return False
    return user.subscription_status == "active"


async def get_user_count() -> int:
    async with async_session() as s:
        result = await s.execute(select(func.count(User.id)))
        return result.scalar_one()


async def get_onboarded_count() -> int:
    async with async_session() as s:
        result = await s.execute(
            select(func.count(User.id)).where(User.onboarding_done == True)  # noqa: E712
        )
        return result.scalar_one()
