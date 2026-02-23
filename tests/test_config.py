"""Tests for config.py — sports structure, risk profiles."""

import config


class TestSportsStructure:
    def test_sa_sports_not_empty(self):
        assert len(config.SA_SPORTS) > 0

    def test_global_sports_not_empty(self):
        assert len(config.GLOBAL_SPORTS) > 0

    def test_all_sports_combined(self):
        total = len(config.SA_SPORTS) + len(config.GLOBAL_SPORTS)
        assert len(config.ALL_SPORTS) == total

    def test_sport_def_has_required_fields(self):
        for sport in config.SA_SPORTS + config.GLOBAL_SPORTS:
            assert sport.key, "sport must have a key"
            assert sport.label, "sport must have a label"
            assert sport.emoji, "sport must have an emoji"
            assert isinstance(sport.leagues, list)

    def test_sa_sports_contain_psl(self):
        keys = [s.key for s in config.SA_SPORTS]
        assert "psl" in keys

    def test_sa_sports_contain_rugby(self):
        keys = [s.key for s in config.SA_SPORTS]
        assert any(k in keys for k in ("urc", "super_rugby", "currie_cup"))

    def test_sa_sports_contain_cricket(self):
        keys = [s.key for s in config.SA_SPORTS]
        assert "csa_cricket" in keys

    def test_global_sports_contain_epl(self):
        keys = [s.key for s in config.GLOBAL_SPORTS]
        assert "epl" in keys

    def test_global_sports_contain_nba(self):
        keys = [s.key for s in config.GLOBAL_SPORTS]
        assert "nba" in keys

    def test_global_sports_contain_ucl(self):
        keys = [s.key for s in config.GLOBAL_SPORTS]
        assert "ucl" in keys

    def test_all_sports_unique_keys(self):
        keys = [s.key for s in config.SA_SPORTS + config.GLOBAL_SPORTS]
        assert len(keys) == len(set(keys)), "duplicate sport keys found"

    def test_sports_map_only_has_api_keys(self):
        """SPORTS_MAP should only contain sports with real API keys."""
        for key, api_key in config.SPORTS_MAP.items():
            assert api_key is not None
            assert api_key != ""


class TestRiskProfiles:
    def test_risk_profiles_exist(self):
        assert len(config.RISK_PROFILES) == 3

    def test_risk_profile_keys(self):
        assert "conservative" in config.RISK_PROFILES
        assert "moderate" in config.RISK_PROFILES
        assert "aggressive" in config.RISK_PROFILES

    def test_risk_profile_has_label(self):
        for key, prof in config.RISK_PROFILES.items():
            assert "label" in prof
            assert "kelly_fraction" in prof
            assert "max_stake_pct" in prof

    def test_kelly_fraction_ordering(self):
        c = config.RISK_PROFILES["conservative"]["kelly_fraction"]
        m = config.RISK_PROFILES["moderate"]["kelly_fraction"]
        a = config.RISK_PROFILES["aggressive"]["kelly_fraction"]
        assert c < m < a
