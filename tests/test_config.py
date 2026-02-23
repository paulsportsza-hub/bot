"""Tests for config.py — sport categories, leagues, risk profiles, aliases."""

import config


class TestSportsStructure:
    def test_sports_not_empty(self):
        assert len(config.SPORTS) > 0

    def test_all_sports_matches_sports_list(self):
        assert len(config.ALL_SPORTS) == len(config.SPORTS)

    def test_sport_def_has_required_fields(self):
        for sport in config.SPORTS:
            assert sport.key, "sport must have a key"
            assert sport.label, "sport must have a label"
            assert sport.emoji, "sport must have an emoji"
            assert isinstance(sport.leagues, list)
            assert sport.fav_type in ("team", "player", "fighter", "driver", "skip")

    def test_sport_categories(self):
        keys = {s.key for s in config.SPORTS}
        assert "soccer" in keys
        assert "rugby" in keys
        assert "cricket" in keys
        assert "tennis" in keys
        assert "boxing" in keys
        assert "mma" in keys
        assert "basketball" in keys
        assert "golf" in keys
        assert "motorsport" in keys
        assert "horse_racing" in keys

    def test_all_sports_unique_keys(self):
        keys = [s.key for s in config.SPORTS]
        assert len(keys) == len(set(keys)), "duplicate sport keys found"

    def test_all_leagues_not_empty(self):
        assert len(config.ALL_LEAGUES) > 0

    def test_league_keys_unique(self):
        keys: list[str] = []
        for s in config.SPORTS:
            for lg in s.leagues:
                keys.append(lg.key)
        assert len(keys) == len(set(keys)), "duplicate league keys found"

    def test_league_sport_mapping(self):
        """Every league should map back to its parent sport."""
        for s in config.SPORTS:
            for lg in s.leagues:
                assert config.LEAGUE_SPORT[lg.key] == s.key

    def test_sports_map_only_has_api_keys(self):
        """SPORTS_MAP should only contain leagues with real API keys."""
        for key, api_key in config.SPORTS_MAP.items():
            assert api_key is not None
            assert api_key != ""

    def test_soccer_has_psl(self):
        soccer = config.ALL_SPORTS["soccer"]
        lg_keys = [lg.key for lg in soccer.leagues]
        assert "psl" in lg_keys

    def test_soccer_has_epl(self):
        soccer = config.ALL_SPORTS["soccer"]
        lg_keys = [lg.key for lg in soccer.leagues]
        assert "epl" in lg_keys

    def test_basketball_has_nba(self):
        bball = config.ALL_SPORTS["basketball"]
        lg_keys = [lg.key for lg in bball.leagues]
        assert "nba" in lg_keys

    def test_rugby_has_urc(self):
        rugby = config.ALL_SPORTS["rugby"]
        lg_keys = [lg.key for lg in rugby.leagues]
        assert "urc" in lg_keys

    def test_cricket_has_ipl(self):
        cricket = config.ALL_SPORTS["cricket"]
        lg_keys = [lg.key for lg in cricket.leagues]
        assert "ipl" in lg_keys


class TestFavTypes:
    def test_soccer_is_team(self):
        assert config.ALL_SPORTS["soccer"].fav_type == "team"

    def test_tennis_is_player(self):
        assert config.ALL_SPORTS["tennis"].fav_type == "player"

    def test_boxing_is_fighter(self):
        assert config.ALL_SPORTS["boxing"].fav_type == "fighter"

    def test_mma_is_fighter(self):
        assert config.ALL_SPORTS["mma"].fav_type == "fighter"

    def test_motorsport_is_driver(self):
        assert config.ALL_SPORTS["motorsport"].fav_type == "driver"

    def test_horse_racing_is_skip(self):
        assert config.ALL_SPORTS["horse_racing"].fav_type == "skip"

    def test_golf_is_player(self):
        assert config.ALL_SPORTS["golf"].fav_type == "player"


class TestFavLabels:
    def test_team_label(self):
        sport = config.ALL_SPORTS["soccer"]
        assert "team" in config.fav_label(sport)

    def test_player_label(self):
        sport = config.ALL_SPORTS["tennis"]
        assert "player" in config.fav_label(sport)

    def test_fighter_label(self):
        sport = config.ALL_SPORTS["boxing"]
        assert "fighter" in config.fav_label(sport)

    def test_driver_label(self):
        sport = config.ALL_SPORTS["motorsport"]
        assert "driver" in config.fav_label(sport)

    def test_plural_teams(self):
        sport = config.ALL_SPORTS["soccer"]
        assert "teams" in config.fav_label_plural(sport)


class TestTopTeams:
    def test_top_teams_not_empty(self):
        assert len(config.TOP_TEAMS) > 0

    def test_psl_teams(self):
        assert "Kaizer Chiefs" in config.TOP_TEAMS["psl"]
        assert "Orlando Pirates" in config.TOP_TEAMS["psl"]

    def test_epl_teams(self):
        assert "Arsenal" in config.TOP_TEAMS["epl"]
        assert "Liverpool" in config.TOP_TEAMS["epl"]

    def test_nba_teams(self):
        assert "Lakers" in config.TOP_TEAMS["nba"]

    def test_ufc_fighters(self):
        assert "Dricus Du Plessis" in config.TOP_TEAMS["ufc"]

    def test_atp_players(self):
        assert "Djokovic" in config.TOP_TEAMS["atp"]

    def test_f1_drivers(self):
        assert "Max Verstappen" in config.TOP_TEAMS["f1"]


class TestTeamAliases:
    def test_aliases_not_empty(self):
        assert len(config.TEAM_ALIASES) > 0

    def test_sa_aliases(self):
        assert config.TEAM_ALIASES["chiefs"] == "Kaizer Chiefs"
        assert config.TEAM_ALIASES["pirates"] == "Orlando Pirates"
        assert config.TEAM_ALIASES["sundowns"] == "Mamelodi Sundowns"

    def test_epl_aliases(self):
        assert config.TEAM_ALIASES["man utd"] == "Man United"
        assert config.TEAM_ALIASES["gooners"] == "Arsenal"

    def test_mma_aliases(self):
        assert config.TEAM_ALIASES["dricus"] == "Dricus Du Plessis"

    def test_f1_aliases(self):
        assert config.TEAM_ALIASES["max"] == "Max Verstappen"

    def test_all_aliases_lowercase(self):
        for key in config.TEAM_ALIASES:
            assert key == key.lower(), f"alias key '{key}' is not lowercase"


class TestSportDisplay:
    def test_sport_display_not_empty(self):
        assert len(config.SPORT_DISPLAY) > 0

    def test_soccer_display(self):
        assert config.SPORT_DISPLAY["Soccer"]["emoji"] == "⚽"
        assert config.SPORT_DISPLAY["Soccer"]["entity"] == "team"
        assert config.SPORT_DISPLAY["Soccer"]["entities"] == "teams"

    def test_tennis_display(self):
        assert config.SPORT_DISPLAY["Tennis"]["entity"] == "player"

    def test_boxing_display(self):
        assert config.SPORT_DISPLAY["Boxing"]["entity"] == "fighter"

    def test_mma_display(self):
        assert config.SPORT_DISPLAY["Mixed Martial Arts"]["entity"] == "fighter"

    def test_all_entries_have_required_keys(self):
        for group, info in config.SPORT_DISPLAY.items():
            assert "emoji" in info, f"{group} missing emoji"
            assert "entity" in info, f"{group} missing entity"
            assert "entities" in info, f"{group} missing entities"


class TestSAPriorityGroups:
    def test_sa_priority_not_empty(self):
        assert len(config.SA_PRIORITY_GROUPS) > 0

    def test_soccer_first(self):
        assert config.SA_PRIORITY_GROUPS[0] == "Soccer"

    def test_rugby_in_top_3(self):
        assert "Rugby Union" in config.SA_PRIORITY_GROUPS[:3]

    def test_cricket_in_top_3(self):
        assert "Cricket" in config.SA_PRIORITY_GROUPS[:3]

    def test_all_groups_in_sport_display(self):
        for group in config.SA_PRIORITY_GROUPS:
            assert group in config.SPORT_DISPLAY, f"{group} not in SPORT_DISPLAY"


class TestSportHelpers:
    def test_get_sport_emoji_known(self):
        assert config.get_sport_emoji("Soccer") == "⚽"
        assert config.get_sport_emoji("Tennis") == "🎾"

    def test_get_sport_emoji_unknown(self):
        assert config.get_sport_emoji("Curling") == "🏅"

    def test_get_entity_label_team(self):
        assert config.get_entity_label("Soccer") == "team"
        assert config.get_entity_label("Soccer", plural=True) == "teams"

    def test_get_entity_label_player(self):
        assert config.get_entity_label("Tennis") == "player"
        assert config.get_entity_label("Tennis", plural=True) == "players"

    def test_get_entity_label_fighter(self):
        assert config.get_entity_label("Boxing") == "fighter"

    def test_get_entity_label_unknown(self):
        assert config.get_entity_label("Unknown Sport") == "team"
        assert config.get_entity_label("Unknown Sport", plural=True) == "teams"

    def test_odds_api_base_alias(self):
        assert config.ODDS_API_BASE == config.ODDS_BASE_URL


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
