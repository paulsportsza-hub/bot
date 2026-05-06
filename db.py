"""Async SQLAlchemy models & helpers for MzansiEdge."""

from __future__ import annotations

import datetime as dt
from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, Integer, String, Text,
    UniqueConstraint, delete, func, select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

import config

engine = create_async_engine(config.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("founding_slot_number", name="uq_users_founding_slot_number"),
    )

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
    # Subscription
    email: Mapped[str | None] = mapped_column(String(255))  # for Stitch
    subscription_status: Mapped[str | None] = mapped_column(String(32))  # "active" | "cancelled" | None
    subscription_code: Mapped[str | None] = mapped_column(String(128))  # Stitch subscription code
    plan_code: Mapped[str | None] = mapped_column(String(128))  # Stitch plan/product code
    subscription_started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # Tier system
    user_tier: Mapped[str | None] = mapped_column(String(32), default="bronze")  # "bronze" | "gold" | "diamond"
    tier_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    is_founding_member: Mapped[bool] = mapped_column(Boolean, default=False)
    founding_slot_number: Mapped[int | None] = mapped_column(Integer)
    founding_price_cents: Mapped[int | None] = mapped_column(Integer)
    founding_paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    payment_provider: Mapped[str | None] = mapped_column(String(32))
    payment_provider_reference: Mapped[str | None] = mapped_column(String(255))
    billing_status: Mapped[str | None] = mapped_column(String(64))
    # Reverse trial
    trial_status: Mapped[str | None] = mapped_column(String(32))  # active/expired/restarted/none
    trial_start_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    trial_end_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    trial_restart_used: Mapped[bool] = mapped_column(Boolean, default=False)
    # Wave 25A: Anti-fatigue + re-engagement
    last_active_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    nudge_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    muted_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    daily_push_count: Mapped[int] = mapped_column(Integer, default=0)
    last_push_date: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD
    consecutive_misses: Mapped[int] = mapped_column(Integer, default=0)


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


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("provider", "provider_payment_id", name="uq_payments_provider_payment_id"),
        UniqueConstraint("provider", "provider_reference", name="uq_payments_provider_reference"),
        UniqueConstraint("provider", "provider_event_id", name="uq_payments_provider_event_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    provider: Mapped[str] = mapped_column(String(32), default="stitch")
    plan_code: Mapped[str] = mapped_column(String(128))
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="ZAR")
    provider_payment_id: Mapped[str | None] = mapped_column(String(128))
    provider_reference: Mapped[str] = mapped_column(String(255))
    provider_event_id: Mapped[str | None] = mapped_column(String(128))
    checkout_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), default="pending")
    billing_status: Mapped[str | None] = mapped_column(String(64))
    is_founding: Mapped[bool] = mapped_column(Boolean, default=False)
    founding_slot_number: Mapped[int | None] = mapped_column(Integer)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    raw_event: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── Helper functions ──────────────────────────────────────

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # SQLite column migration for existing databases
    await _migrate_columns()
    await _ensure_payments_table()
    await _ensure_founding_indexes()
    await _backfill_founding_state()
    # Wave 25C: ensure user_edge_views table exists
    await _ensure_edge_views_table()


async def _migrate_columns() -> None:
    """Add new columns to existing SQLite tables if missing."""
    import aiosqlite
    db_url = config.DATABASE_URL
    if "sqlite" not in db_url:
        return
    db_path = config.DATABASE_PATH
    if db_path is None:
        return
    try:
        async with aiosqlite.connect(db_path.as_posix()) as conn:
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
                ("user_tier", "'bronze'"),
                ("tier_expires_at", "NULL"),
                ("is_founding_member", "0"),
                ("founding_slot_number", "NULL"),
                ("founding_price_cents", "NULL"),
                ("founding_paid_at", "NULL"),
                ("payment_provider", "NULL"),
                ("payment_provider_reference", "NULL"),
                ("billing_status", "NULL"),
                ("trial_status", "NULL"),
                ("trial_start_date", "NULL"),
                ("trial_end_date", "NULL"),
                ("trial_restart_used", "0"),
                ("last_active_at", "NULL"),
                ("nudge_sent_at", "NULL"),
                ("muted_until", "NULL"),
                ("daily_push_count", "0"),
                ("last_push_date", "NULL"),
                ("consecutive_misses", "0"),
                ("stitch_subscription_id", "NULL"),
                ("subscription_billing_day", "NULL"),
                ("subscription_next_charge_at", "NULL"),
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


async def _ensure_payments_table() -> None:
    """Create payments table for narrow founding/payment tracking."""
    ddl = """
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL DEFAULT 'stitch',
            plan_code TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'ZAR',
            provider_payment_id TEXT,
            provider_reference TEXT NOT NULL,
            provider_event_id TEXT,
            checkout_url TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            billing_status TEXT,
            is_founding INTEGER NOT NULL DEFAULT 0,
            founding_slot_number INTEGER,
            confirmed_at DATETIME,
            refunded_at DATETIME,
            raw_event TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_provider_payment
            ON payments(provider, provider_payment_id)
            WHERE provider_payment_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_provider_reference
            ON payments(provider, provider_reference);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_provider_event
            ON payments(provider, provider_event_id)
            WHERE provider_event_id IS NOT NULL;
    """

    db_url = config.DATABASE_URL
    if "sqlite" not in db_url:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(ddl)
        return

    db_path = config.DATABASE_PATH
    if db_path is None:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(ddl)
        return

    import aiosqlite

    try:
        async with aiosqlite.connect(db_path.as_posix()) as conn:
            await conn.executescript(ddl)
            await conn.commit()
    except Exception:
        pass


async def _ensure_founding_indexes() -> None:
    """Backfill indexes required for founding slot uniqueness."""
    ddl = """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_founding_slot_number
            ON users(founding_slot_number)
            WHERE founding_slot_number IS NOT NULL;
    """
    db_url = config.DATABASE_URL
    if "sqlite" not in db_url:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(ddl)
        return

    db_path = config.DATABASE_PATH
    if db_path is None:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(ddl)
        return

    import aiosqlite

    try:
        async with aiosqlite.connect(db_path.as_posix()) as conn:
            await conn.executescript(ddl)
            await conn.commit()
    except Exception:
        pass


async def _backfill_founding_state() -> None:
    """Populate missing founding metadata for legacy founding users."""
    async with async_session() as s:
        result = await s.execute(
            select(User).where(
                User.is_founding_member == True,  # noqa: E712
                User.founding_price_cents == None,  # noqa: E711
            )
        )
        changed = False
        for user in result.scalars().all():
            if user.founding_price_cents is None:
                user.founding_price_cents = config.FOUNDING_MEMBER_PRICE
            if not user.payment_provider:
                user.payment_provider = "stitch"
            if not user.billing_status:
                user.billing_status = "active"
            changed = True
        if changed:
            await s.commit()


async def _ensure_edge_views_table() -> None:
    """Create user_edge_views table if it doesn't exist (Wave 25C)."""
    import aiosqlite
    db_url = config.DATABASE_URL
    if "sqlite" not in db_url:
        return
    db_path = config.DATABASE_PATH
    if db_path is None:
        # For in-memory DBs, use engine directly
        async with engine.begin() as conn:
            await conn.exec_driver_sql("""
                CREATE TABLE IF NOT EXISTS user_edge_views (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    edge_id TEXT NOT NULL,
                    edge_tier TEXT NOT NULL,
                    viewed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, edge_id)
                )
            """)
        return
    try:
        async with aiosqlite.connect(db_path.as_posix()) as conn:
            await conn.executescript("""
                CREATE TABLE IF NOT EXISTS user_edge_views (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    edge_id TEXT NOT NULL,
                    edge_tier TEXT NOT NULL,
                    viewed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, edge_id)
                );
            """)
            await conn.commit()
    except Exception:
        pass


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


async def clear_user_sport(user_id: int, sport_key: str) -> None:
    """Delete all saved prefs for a single sport."""
    async with async_session() as s:
        await s.execute(
            delete(UserSportPref).where(
                UserSportPref.user_id == user_id,
                UserSportPref.sport_key == sport_key,
            )
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


async def get_recent_wins(limit: int = 5) -> list[Tip]:
    """Return the most recently resolved winning edges."""
    async with async_session() as s:
        result = await s.execute(
            select(Tip)
            .where(Tip.result == "win")
            .order_by(Tip.created_at.desc())
            .limit(limit)
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


async def get_all_onboarded_users() -> list[User]:
    """Get all active, onboarded users (for monthly broadcast)."""
    async with async_session() as s:
        result = await s.execute(
            select(User).where(
                User.onboarding_done == True,  # noqa: E712
                User.is_active == True,  # noqa: E712
            )
        )
        return list(result.scalars().all())


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


async def update_user_stitch_subscription_id(user_id: int, subscription_id: str) -> None:
    """Store Stitch subscription ID on successful recurring subscription creation."""
    import aiosqlite
    db_path = config.DATABASE_PATH
    if db_path is None:
        return
    async with aiosqlite.connect(db_path.as_posix()) as conn:
        await conn.execute(
            "UPDATE users SET stitch_subscription_id = ? WHERE id = ?",
            (subscription_id, user_id),
        )
        await conn.commit()


async def get_payment_by_reference(provider: str, provider_reference: str) -> Payment | None:
    async with async_session() as s:
        result = await s.execute(
            select(Payment).where(
                Payment.provider == provider,
                Payment.provider_reference == provider_reference,
            )
        )
        return result.scalars().first()


async def get_payment_by_provider_payment_id(provider: str, provider_payment_id: str) -> Payment | None:
    async with async_session() as s:
        result = await s.execute(
            select(Payment).where(
                Payment.provider == provider,
                Payment.provider_payment_id == provider_payment_id,
            )
        )
        return result.scalars().first()


async def get_open_payment_for_user(user_id: int, plan_code: str, provider: str = "stitch") -> Payment | None:
    """Return the latest non-terminal payment for reuse/idempotency."""
    async with async_session() as s:
        result = await s.execute(
            select(Payment).where(
                Payment.user_id == user_id,
                Payment.plan_code == plan_code,
                Payment.provider == provider,
                Payment.status.in_(["pending", "payment_created", "awaiting_webhook"]),
            ).order_by(Payment.id.desc())
        )
        return result.scalars().first()


async def create_payment_record(
    user_id: int,
    plan_code: str,
    amount_cents: int,
    provider_reference: str,
    *,
    provider: str = "stitch",
    provider_payment_id: str | None = None,
    checkout_url: str | None = None,
    is_founding: bool = False,
    billing_status: str = "awaiting_webhook",
) -> Payment:
    """Persist a new checkout attempt."""
    async with async_session() as s:
        payment = Payment(
            user_id=user_id,
            provider=provider,
            plan_code=plan_code,
            amount_cents=amount_cents,
            provider_reference=provider_reference,
            provider_payment_id=provider_payment_id,
            checkout_url=checkout_url,
            status="payment_created" if provider_payment_id else "pending",
            billing_status=billing_status,
            is_founding=is_founding,
        )
        s.add(payment)
        await s.commit()
        await s.refresh(payment)
        return payment


async def update_payment_checkout(
    payment_id: int,
    *,
    provider_payment_id: str,
    checkout_url: str,
    status: str = "payment_created",
) -> Payment | None:
    async with async_session() as s:
        payment = await s.get(Payment, payment_id)
        if not payment:
            return None
        payment.provider_payment_id = provider_payment_id
        payment.checkout_url = checkout_url
        payment.status = status
        await s.commit()
        await s.refresh(payment)
        return payment


async def get_payment(payment_id: int) -> Payment | None:
    async with async_session() as s:
        return await s.get(Payment, payment_id)


async def mark_payment_refunded(
    provider: str,
    provider_reference: str,
    *,
    refunded_at: dt.datetime | None = None,
) -> Payment | None:
    """Move a refund-pending payment to refunded."""
    async with async_session() as s:
        result = await s.execute(
            select(Payment).where(
                Payment.provider == provider,
                Payment.provider_reference == provider_reference,
            )
        )
        payment = result.scalars().first()
        if not payment:
            return None
        payment.status = "refunded"
        payment.billing_status = "refunded"
        payment.refunded_at = refunded_at or dt.datetime.now(dt.timezone.utc)
        await s.commit()
        await s.refresh(payment)
        return payment


async def activate_subscription(
    user_id: int, subscription_code: str, plan_code: str,
    user_tier: str = "gold",
    tier_expires_at: dt.datetime | None = None,
    payment_provider: str = "stitch",
    payment_reference: str | None = None,
    billing_status: str = "active",
) -> None:
    """Mark user as subscribed after successful Stitch payment."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.subscription_status = "active"
            user.subscription_code = subscription_code
            user.plan_code = plan_code
            user.subscription_started_at = dt.datetime.now(dt.timezone.utc)
            user.user_tier = user_tier
            user.tier_expires_at = tier_expires_at
            user.payment_provider = payment_provider
            user.payment_provider_reference = payment_reference
            user.billing_status = billing_status
            await s.commit()


async def deactivate_subscription(user_id: int) -> None:
    """Deactivate user subscription (cancelled or expired). Resets to bronze tier."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.subscription_status = "cancelled"
            user.user_tier = "bronze"
            user.tier_expires_at = None
            user.billing_status = "cancelled"
            await s.commit()


async def get_user_by_email(email: str) -> User | None:
    """Find a user by email (for webhook resolution)."""
    async with async_session() as s:
        result = await s.execute(select(User).where(User.email == email))
        return result.scalars().first()


def is_premium(user: User | None) -> bool:
    """Check if a user has an active paid subscription (Gold or Diamond)."""
    if not user:
        return False
    tier = getattr(user, "user_tier", None) or "bronze"
    return tier in ("gold", "diamond")


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


async def get_all_sport_prefs() -> list[UserSportPref]:
    """Get ALL sport prefs across all users (for migrations)."""
    async with async_session() as s:
        result = await s.execute(select(UserSportPref))
        return list(result.scalars().all())


# ── Tier helpers ─────────────────────────────────────────────


def _resolve_tier_from_subscription(user: "User") -> str | None:
    """If DB tier=bronze but subscription is active, derive tier from plan_code.

    Handles the case where /qa reset or a webhook failure left user_tier='bronze'
    while subscription_status='active'. Returns the derived tier or None.
    """
    sub_status = getattr(user, "subscription_status", None)
    if sub_status != "active":
        return None
    plan = getattr(user, "plan_code", None) or ""
    # Build tier map from STITCH_PRODUCTS + legacy plan codes
    tier_map: dict[str, str] = {"stitch_premium": "gold"}
    for pkey, pval in config.STITCH_PRODUCTS.items():
        tier_map[pkey] = pval.get("tier", "gold")
    return tier_map.get(plan) or None


async def get_user_tier(user_id: int) -> str:
    """Return the user's effective subscription tier (default 'bronze').

    Reconciles user_tier with subscription_status: if user_tier='bronze' but
    subscription_status='active', derives the correct tier from plan_code.
    Also enforces read-time expiry check (3-day grace) so stale gold/diamond
    rows don't grant access after expiry without waiting for the hourly cron.
    This prevents stale bronze state after /qa reset or webhook failures.
    """
    async with async_session() as s:
        user = await s.get(User, user_id)
        if not user:
            return "bronze"
        tier = getattr(user, "user_tier", None) or "bronze"
        if tier == "bronze":
            derived = _resolve_tier_from_subscription(user)
            if derived in ("gold", "diamond"):
                tier = derived
        # Read-time expiry enforcement (no DB writes — cron handles settlement)
        if tier in ("gold", "diamond"):
            expires_at = getattr(user, "tier_expires_at", None)
            if expires_at is not None:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=dt.timezone.utc)
                now = dt.datetime.now(dt.timezone.utc)
                grace_end = expires_at + dt.timedelta(days=3)
                if now > grace_end:
                    return "bronze"
        return tier


async def set_user_tier(
    user_id: int,
    tier: str,
    expires_at: dt.datetime | None = None,
) -> None:
    """Set a user's subscription tier and optional expiry."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.user_tier = tier
            user.tier_expires_at = expires_at
            if tier in ("gold", "diamond"):
                user.subscription_status = "active"
            await s.commit()


async def set_founding_member(user_id: int, is_founding: bool = True) -> None:
    """Mark or unmark a user as a founding member."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.is_founding_member = is_founding
            if is_founding and user.founding_price_cents is None:
                user.founding_price_cents = config.FOUNDING_MEMBER_PRICE
            if is_founding and not user.billing_status:
                user.billing_status = "active"
            await s.commit()


async def get_founding_member_count() -> int:
    """Count users who are founding members."""
    async with async_session() as s:
        result = await s.execute(
            select(func.count(User.id)).where(
                User.is_founding_member == True  # noqa: E712
            )
        )
        return result.scalar_one()


async def get_remaining_founding_slots() -> int:
    sold = await get_founding_member_count()
    return max(config.FOUNDING_MEMBER_SLOTS - sold, 0)


async def get_recent_founding_payments(limit: int = 5) -> list[Payment]:
    async with async_session() as s:
        result = await s.execute(
            select(Payment).where(
                Payment.is_founding == True  # noqa: E712
            ).order_by(Payment.id.desc()).limit(limit)
        )
        return list(result.scalars().all())


async def get_payment_summary() -> dict[str, int]:
    """Aggregate founding payment statuses for admin/status visibility."""
    async with async_session() as s:
        sold_result = await s.execute(
            select(func.count(User.id)).where(
                User.is_founding_member == True  # noqa: E712
            )
        )
        pending_result = await s.execute(
            select(func.count(Payment.id)).where(
                Payment.is_founding == True,  # noqa: E712
                Payment.status.in_(["pending", "payment_created", "awaiting_webhook"]),
            )
        )
        refund_pending_result = await s.execute(
            select(func.count(Payment.id)).where(
                Payment.is_founding == True,  # noqa: E712
                Payment.billing_status == "refund_pending",
            )
        )
        sold = sold_result.scalar_one()
        return {
            "sold": sold,
            "pending": pending_result.scalar_one(),
            "refund_pending": refund_pending_result.scalar_one(),
            "remaining": max(config.FOUNDING_MEMBER_SLOTS - sold, 0),
        }


async def apply_payment_event(
    *,
    provider: str,
    provider_reference: str,
    provider_payment_id: str,
    provider_event_id: str | None,
    plan_code: str,
    amount_cents: int,
    event_status: str,
    billing_status: str,
    raw_event: str | None,
) -> dict[str, object]:
    """Apply a provider event idempotently and return a structured outcome."""
    for _attempt in range(3):
        outcome: dict[str, object] = {
            "outcome": "ignored",
            "user_id": None,
            "slot_number": None,
            "payment_status": event_status,
        }
        now = dt.datetime.now(dt.timezone.utc)

        async with async_session() as s:
            if provider_event_id:
                existing_event = await s.execute(
                    select(Payment).where(
                        Payment.provider == provider,
                        Payment.provider_event_id == provider_event_id,
                    )
                )
                if existing_event.scalars().first():
                    outcome["outcome"] = "duplicate_webhook"
                    return outcome

            result = await s.execute(
                select(Payment).where(
                    Payment.provider == provider,
                    Payment.provider_reference == provider_reference,
                )
            )
            payment = result.scalars().first()
            if not payment:
                payment = Payment(
                    user_id=0,
                    provider=provider,
                    plan_code=plan_code,
                    amount_cents=amount_cents,
                    provider_reference=provider_reference,
                    provider_payment_id=provider_payment_id,
                    provider_event_id=provider_event_id,
                    status=event_status,
                    billing_status=billing_status,
                    is_founding=plan_code == "founding_diamond",
                    raw_event=raw_event,
                )
                s.add(payment)
                await s.flush()

            payment.provider_payment_id = provider_payment_id
            payment.provider_event_id = provider_event_id
            payment.raw_event = raw_event
            payment.amount_cents = amount_cents
            payment.plan_code = plan_code
            payment.is_founding = plan_code == "founding_diamond"

            user = await s.get(User, payment.user_id) if payment.user_id else None
            if payment.user_id:
                outcome["user_id"] = payment.user_id

            terminal_successes = {"confirmed", "confirmed_no_slot", "refunded"}
            if event_status == "confirmed" and payment.status in terminal_successes:
                outcome["outcome"] = "duplicate_payment"
                outcome["slot_number"] = payment.founding_slot_number
                return outcome

            if event_status in {"cancelled", "failed", "expired"}:
                payment.status = event_status
                payment.billing_status = billing_status
                matched_active_subscription = (
                    user is not None
                    and event_status in {"cancelled", "expired"}
                    and plan_code != "founding_diamond"
                    and user.subscription_status == "active"
                    and bool(provider_payment_id)
                    and user.subscription_code == provider_payment_id
                )
                if matched_active_subscription:
                    user.subscription_status = "cancelled"
                    user.user_tier = "bronze"
                    user.tier_expires_at = None
                    user.billing_status = billing_status
                    outcome["subscription_deactivated"] = True
                elif user and user.subscription_status != "active":
                    user.billing_status = billing_status
                await s.commit()
                outcome["outcome"] = event_status
                return outcome

            if not user:
                payment.status = "failed"
                payment.billing_status = "user_not_found"
                await s.commit()
                outcome["outcome"] = "user_not_found"
                return outcome

            if plan_code == "founding_diamond" and user.is_founding_member and user.founding_slot_number is not None:
                payment.status = "confirmed"
                payment.billing_status = "active"
                payment.confirmed_at = payment.confirmed_at or now
                payment.founding_slot_number = user.founding_slot_number
                outcome["outcome"] = "already_founding_member"
                outcome["slot_number"] = user.founding_slot_number
            elif plan_code == "founding_diamond":
                next_slot = await s.scalar(
                    select(func.max(User.founding_slot_number)).where(
                        User.founding_slot_number != None  # noqa: E711
                    )
                )
                next_slot = int(next_slot or 0) + 1
                if next_slot > config.FOUNDING_MEMBER_SLOTS:
                    payment.status = "confirmed_no_slot"
                    payment.billing_status = "refund_pending"
                    payment.confirmed_at = now
                    user.billing_status = "refund_pending"
                    outcome["outcome"] = "no_slot_available"
                else:
                    expires = now + dt.timedelta(days=365)
                    user.subscription_status = "active"
                    user.subscription_code = provider_payment_id
                    user.plan_code = plan_code
                    user.subscription_started_at = now
                    user.user_tier = "diamond"
                    user.tier_expires_at = expires
                    user.is_founding_member = True
                    user.founding_slot_number = next_slot
                    user.founding_price_cents = config.FOUNDING_MEMBER_PRICE
                    user.founding_paid_at = now
                    user.payment_provider = provider
                    user.payment_provider_reference = provider_reference
                    user.billing_status = "active"
                    payment.status = "confirmed"
                    payment.billing_status = "active"
                    payment.confirmed_at = now
                    payment.founding_slot_number = next_slot
                    outcome["outcome"] = "confirmed"
                    outcome["slot_number"] = next_slot
            else:
                expires = now + (dt.timedelta(days=365) if "annual" in plan_code else dt.timedelta(days=30))
                user.subscription_status = "active"
                user.subscription_code = provider_payment_id
                user.plan_code = plan_code
                user.subscription_started_at = now
                user.user_tier = "diamond" if "diamond" in plan_code else "gold"
                user.tier_expires_at = expires
                user.payment_provider = provider
                user.payment_provider_reference = provider_reference
                user.billing_status = "active"
                payment.status = "confirmed"
                payment.billing_status = "active"
                payment.confirmed_at = now
                outcome["outcome"] = "confirmed"

            try:
                await s.commit()
                outcome["user_id"] = user.id
                return outcome
            except IntegrityError as exc:
                await s.rollback()
                if "founding_slot_number" not in str(exc):
                    raise

    raise RuntimeError("Founding slot assignment could not be completed after retries")


async def get_expired_paid_users() -> list[tuple[int, str]]:
    """Return (user_id, user_tier) for paid users whose tier has expired."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    async with async_session() as s:
        result = await s.execute(
            select(User.id, User.user_tier).where(
                User.user_tier.in_(["gold", "diamond"]),
                User.tier_expires_at != None,  # noqa: E711
                User.tier_expires_at < now,
            )
        )
        return [(row[0], row[1]) for row in result.all()]


async def get_active_diamond_users() -> list[int]:
    """Return user IDs of active Diamond subscribers for proactive edge DMs (AC-E).

    Used by _fire_diamond_edge_dms in _tier_fire_alerts_job to send canonical
    edge cards to Diamond subscribers on tier-fire. Respects is_active +
    onboarding_done; mute/push-cap checked per-user by _can_send_notification.
    """
    async with async_session() as s:
        result = await s.execute(
            select(User.id).where(
                User.user_tier == "diamond",
                User.is_active == True,  # noqa: E712
                User.onboarding_done == True,  # noqa: E712
            )
        )
        return [row[0] for row in result.all()]


# ── Trial helpers ────────────────────────────────────────────


async def start_trial(user_id: int, days: int = 7) -> None:
    """Activate Diamond trial for a new user."""
    now = dt.datetime.now(dt.timezone.utc)
    end = now + dt.timedelta(days=days)
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.user_tier = "diamond"
            user.trial_status = "active"
            user.trial_start_date = now
            user.trial_end_date = end
            await s.commit()


async def expire_trial(user_id: int) -> None:
    """Downgrade trial user to bronze."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.user_tier = "bronze"
            user.trial_status = "expired"
            await s.commit()


async def restart_trial(user_id: int) -> bool:
    """3-day Diamond restart. Returns True if successful, False if already used."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if not user or user.trial_restart_used:
            return False
        # Must have had a prior trial (expired or active)
        if not user.trial_status or user.trial_status == "none":
            return False
        now = dt.datetime.now(dt.timezone.utc)
        user.user_tier = "diamond"
        user.trial_status = "restarted"
        user.trial_start_date = now
        user.trial_end_date = now + dt.timedelta(days=3)
        user.trial_restart_used = True
        await s.commit()
        return True


async def get_trial_users_at_day(day: int) -> list[User]:
    """Get users whose trial started exactly `day` days ago."""
    now = dt.datetime.now(dt.timezone.utc)
    target_start = now - dt.timedelta(days=day)
    window_start = target_start.replace(hour=0, minute=0, second=0, microsecond=0)
    window_end = window_start + dt.timedelta(days=1)
    async with async_session() as s:
        result = await s.execute(
            select(User).where(
                User.trial_status.in_(["active", "restarted"]),
                User.trial_start_date >= window_start,
                User.trial_start_date < window_end,
            )
        )
        return list(result.scalars().all())


async def get_expired_trial_users() -> list[User]:
    """Get trial users whose trial_end_date has passed and haven't been downgraded."""
    now = dt.datetime.now(dt.timezone.utc)
    async with async_session() as s:
        result = await s.execute(
            select(User).where(
                User.trial_status.in_(["active", "restarted"]),
                User.trial_end_date != None,  # noqa: E711
                User.trial_end_date < now,
                User.subscription_status != "active",
            )
        )
        return list(result.scalars().all())


async def is_trial_active(user_id: int) -> bool:
    """Check if user has an active trial."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if not user:
            return False
        if user.trial_status not in ("active", "restarted"):
            return False
        if user.trial_end_date is None:
            return False
        end = user.trial_end_date
        now = dt.datetime.now(dt.timezone.utc)
        # Handle naive datetimes from SQLite
        if end.tzinfo is None:
            end = end.replace(tzinfo=dt.timezone.utc)
        return end > now


async def get_trial_stats(user_id: int) -> dict:
    """Get trial usage stats for a user."""
    detail_views = 0
    try:
        from db_connection import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT COUNT(*) FROM daily_tip_views WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        detail_views = row[0] if row else 0
    except Exception:
        pass

    # Calculate days remaining
    days_remaining = 0
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user and user.trial_end_date:
            end = user.trial_end_date
            now = dt.datetime.now(dt.timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=dt.timezone.utc)
            delta = (end - now).days
            days_remaining = max(0, delta)

    return {"detail_views": detail_views, "days_remaining": days_remaining}


# ── Wave 25A: Anti-fatigue + re-engagement helpers ────────────


async def update_last_active(user_id: int) -> None:
    """Set last_active_at = now() for a user."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.last_active_at = dt.datetime.now(dt.timezone.utc)
            await s.commit()


async def get_inactive_users(hours: int = 72, nudge_cooldown_days: int = 7) -> list[User]:
    """Get onboarded, active users inactive for >= `hours` who haven't been nudged within `nudge_cooldown_days`."""
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=hours)
    cooldown_cutoff = now - dt.timedelta(days=nudge_cooldown_days)
    async with async_session() as s:
        result = await s.execute(
            select(User).where(
                User.onboarding_done == True,  # noqa: E712
                User.is_active == True,  # noqa: E712
                User.last_active_at != None,  # noqa: E711
                User.last_active_at < cutoff,
                # Nudge cooldown: never nudged OR nudged before cooldown
                (User.nudge_sent_at == None) | (User.nudge_sent_at < cooldown_cutoff),  # noqa: E711
            )
        )
        return list(result.scalars().all())


async def set_muted_until(user_id: int, until_dt: dt.datetime | None) -> None:
    """Set or clear the user's muted_until timestamp."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.muted_until = until_dt
            await s.commit()


async def is_muted(user_id: int) -> bool:
    """Check if user is currently muted (muted_until > now)."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if not user or not user.muted_until:
            return False
        muted = user.muted_until
        now = dt.datetime.now(dt.timezone.utc)
        if muted.tzinfo is None:
            muted = muted.replace(tzinfo=dt.timezone.utc)
        return muted > now


async def increment_push_count(user_id: int) -> None:
    """Bump daily_push_count, resetting if the date has changed."""
    today = dt.date.today().isoformat()
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            if user.last_push_date != today:
                user.daily_push_count = 1
                user.last_push_date = today
            else:
                user.daily_push_count = (user.daily_push_count or 0) + 1
            await s.commit()


async def get_push_count(user_id: int) -> int:
    """Return today's push count (0 if new day or no user)."""
    today = dt.date.today().isoformat()
    async with async_session() as s:
        user = await s.get(User, user_id)
        if not user:
            return 0
        if user.last_push_date != today:
            return 0
        return user.daily_push_count or 0


async def update_consecutive_misses(user_id: int, count: int) -> None:
    """Set the consecutive_misses counter."""
    async with async_session() as s:
        user = await s.get(User, user_id)
        if user:
            user.consecutive_misses = count
            await s.commit()


# ── Wave 25C: Edge view tracking helpers ─────────────────


async def log_edge_view(user_id: int, edge_id: str, edge_tier: str) -> None:
    """Record that a user viewed an edge. INSERT OR IGNORE (dedup on user+edge)."""
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "INSERT OR IGNORE INTO user_edge_views (user_id, edge_id, edge_tier) VALUES (?, ?, ?)",
            (user_id, edge_id, edge_tier),
        )


async def get_edge_viewers(edge_id: str) -> list[dict]:
    """Get all users who viewed a specific edge."""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT user_id, edge_tier, viewed_at FROM user_edge_views WHERE edge_id = ?",
            (edge_id,),
        )
        return [{"user_id": row[0], "edge_tier": row[1], "viewed_at": row[2]} for row in result]


async def get_edges_viewed_by_user(user_id: int, since_hours: int = 48) -> list[dict]:
    """Get edges viewed by a user in the last N hours."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=since_hours)).isoformat()
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT edge_id, edge_tier, viewed_at FROM user_edge_views WHERE user_id = ? AND viewed_at > ?",
            (user_id, cutoff),
        )
        return [{"edge_id": row[0], "edge_tier": row[1], "viewed_at": row[2]} for row in result]


async def get_user_edge_view_summary(user_id: int, since_hours: int = 168) -> dict[str, int]:
    """Return total and recent edge-view counts from the existing user_edge_views table."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=since_hours)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            """
            SELECT
                COUNT(*) AS total_views,
                COALESCE(SUM(CASE WHEN viewed_at >= ? THEN 1 ELSE 0 END), 0) AS recent_views
            FROM user_edge_views
            WHERE user_id = ?
            """,
            (cutoff_str, user_id),
        )
        row = result.fetchone()
    return {
        "total_views": int((row[0] if row else 0) or 0),
        "recent_views": int((row[1] if row else 0) or 0),
    }


async def get_profile_engagement_stats(user_id: int, recent_days: int = 7) -> dict[str, int | None]:
    """Return profile engagement stats from existing user and edge-view tables."""
    view_summary = await get_user_edge_view_summary(user_id, since_hours=recent_days * 24)
    user = await get_user(user_id)

    days_with_mzansiedge: int | None = None
    if user and getattr(user, "joined_at", None):
        joined_at = user.joined_at
        if joined_at.tzinfo is None:
            joined_at = joined_at.replace(tzinfo=dt.timezone.utc)
        days_with_mzansiedge = max(1, (dt.datetime.now(dt.timezone.utc) - joined_at).days + 1)

    return {
        "total_edge_views": int(view_summary.get("total_views", 0) or 0),
        "recent_edge_views": int(view_summary.get("recent_views", 0) or 0),
        "days_with_mzansiedge": days_with_mzansiedge,
    }
