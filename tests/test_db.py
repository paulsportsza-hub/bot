"""Tests for db.py — user CRUD, sport prefs, bet creation."""

from __future__ import annotations

import pytest
import pytest_asyncio

import db


pytestmark = pytest.mark.asyncio


async def test_upsert_user_creates(test_db):
    user = await db.upsert_user(100, "alice", "Alice")
    assert user.id == 100
    assert user.username == "alice"
    assert user.first_name == "Alice"
    assert user.is_active is True
    assert user.onboarding_done is False


async def test_upsert_user_updates(test_db):
    await db.upsert_user(200, "bob", "Bob")
    user = await db.upsert_user(200, "bobby", "Bobby")
    assert user.username == "bobby"
    assert user.first_name == "Bobby"


async def test_get_user(test_db):
    await db.upsert_user(300, "charlie", "Charlie")
    user = await db.get_user(300)
    assert user is not None
    assert user.first_name == "Charlie"


async def test_get_user_not_found(test_db):
    user = await db.get_user(999999)
    assert user is None


async def test_update_user_risk(test_db):
    await db.upsert_user(400, "dave", "Dave")
    await db.update_user_risk(400, "aggressive")
    user = await db.get_user(400)
    assert user.risk_profile == "aggressive"


async def test_update_user_notification_hour(test_db):
    await db.upsert_user(500, "eve", "Eve")
    await db.update_user_notification_hour(500, 18)
    user = await db.get_user(500)
    assert user.notification_hour == 18


async def test_set_onboarding_done(test_db):
    await db.upsert_user(600, "frank", "Frank")
    await db.set_onboarding_done(600)
    user = await db.get_user(600)
    assert user.onboarding_done is True


async def test_save_sport_pref(test_db):
    await db.upsert_user(700, "grace", "Grace")
    pref = await db.save_sport_pref(700, "epl", league="English Premier League", team_name="Arsenal")
    assert pref.user_id == 700
    assert pref.sport_key == "epl"
    assert pref.league == "English Premier League"
    assert pref.team_name == "Arsenal"


async def test_get_user_sport_prefs(test_db):
    await db.upsert_user(800, "hank", "Hank")
    await db.save_sport_pref(800, "psl")
    await db.save_sport_pref(800, "urc")
    prefs = await db.get_user_sport_prefs(800)
    assert len(prefs) == 2
    keys = {p.sport_key for p in prefs}
    assert keys == {"psl", "urc"}


async def test_clear_user_sport_prefs(test_db):
    await db.upsert_user(900, "ivy", "Ivy")
    await db.save_sport_pref(900, "epl")
    await db.clear_user_sport_prefs(900)
    prefs = await db.get_user_sport_prefs(900)
    assert len(prefs) == 0


async def test_save_tip(test_db):
    tip = await db.save_tip("epl", "Arsenal vs Chelsea", "Arsenal win", odds=2.1)
    assert tip.id is not None
    assert tip.sport == "epl"
    assert tip.match == "Arsenal vs Chelsea"
    assert tip.odds == 2.1
    assert tip.result is None


async def test_get_recent_tips(test_db):
    await db.save_tip("epl", "Arsenal vs Liverpool", "Arsenal win")
    await db.save_tip("epl", "Chelsea vs Spurs", "Chelsea win")
    tips = await db.get_recent_tips(limit=5)
    assert len(tips) >= 2


async def test_save_bet(test_db):
    await db.upsert_user(1000, "jack", "Jack")
    tip = await db.save_tip("psl", "Chiefs vs Pirates", "Chiefs win")
    bet = await db.save_bet(1000, tip.id, stake=50.0)
    assert bet.user_id == 1000
    assert bet.tip_id == tip.id
    assert bet.stake == 50.0


async def test_get_user_count(test_db):
    count_before = await db.get_user_count()
    await db.upsert_user(1100, "kate", "Kate")
    count_after = await db.get_user_count()
    assert count_after == count_before + 1
