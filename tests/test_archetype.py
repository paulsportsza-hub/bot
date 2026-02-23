"""Tests for classify_archetype() and DB archetype support."""

from __future__ import annotations

import pytest
import pytest_asyncio

import bot
import db


pytestmark = pytest.mark.asyncio


class TestClassifyArchetype:
    def test_newbie_always_complete_newbie(self):
        archetype, score = bot.classify_archetype("newbie", "moderate", 3)
        assert archetype == "complete_newbie"
        assert score == 3.0

    def test_newbie_ignores_risk_and_sports(self):
        a1, s1 = bot.classify_archetype("newbie", "aggressive", 5)
        a2, s2 = bot.classify_archetype("newbie", "conservative", 1)
        assert a1 == a2 == "complete_newbie"
        assert s1 == s2 == 3.0

    def test_experienced_aggressive_is_eager(self):
        archetype, score = bot.classify_archetype("experienced", "aggressive", 3)
        assert archetype == "eager_bettor"

    def test_experienced_moderate_is_eager(self):
        archetype, score = bot.classify_archetype("experienced", "moderate", 2)
        assert archetype == "eager_bettor"

    def test_experienced_conservative_is_casual(self):
        archetype, score = bot.classify_archetype("experienced", "conservative", 3)
        assert archetype == "casual_fan"

    def test_casual_experience_is_casual_fan(self):
        archetype, score = bot.classify_archetype("casual", "aggressive", 5)
        assert archetype == "casual_fan"

    def test_score_capped_at_10(self):
        _, score = bot.classify_archetype("experienced", "aggressive", 5)
        assert score <= 10.0

    def test_experienced_aggressive_many_sports_high_score(self):
        _, score = bot.classify_archetype("experienced", "aggressive", 4)
        assert score >= 8.0

    def test_casual_conservative_low_score(self):
        _, score = bot.classify_archetype("casual", "conservative", 1)
        assert score == 5.0

    def test_casual_moderate_score(self):
        _, score = bot.classify_archetype("casual", "moderate", 2)
        assert score == 6.0


class TestArchetypeDB:
    async def test_update_user_archetype(self, test_db):
        await db.upsert_user(5001, "arc_user", "Arc")
        await db.update_user_archetype(5001, "eager_bettor", 8.5)
        user = await db.get_user(5001)
        assert user.archetype == "eager_bettor"
        assert user.engagement_score == 8.5

    async def test_default_engagement_score(self, test_db):
        user = await db.upsert_user(5002, "new_user", "New")
        assert user.engagement_score == 5.0

    async def test_default_archetype_is_none(self, test_db):
        user = await db.upsert_user(5003, "fresh", "Fresh")
        assert user.archetype is None

    async def test_reset_clears_archetype(self, test_db):
        await db.upsert_user(5004, "reset_user", "Reset")
        await db.update_user_archetype(5004, "eager_bettor", 9.0)
        await db.reset_user_profile(5004)
        user = await db.get_user(5004)
        assert user.archetype is None
        assert user.engagement_score == 5.0

    async def test_new_columns_exist(self, test_db):
        """Verify new columns (source, fb_click_id, fb_ad_id) are present."""
        user = await db.upsert_user(5005, "col_test", "Col")
        assert user.source is None
        assert user.fb_click_id is None
        assert user.fb_ad_id is None
