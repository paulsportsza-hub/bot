from __future__ import annotations

from validators.sport_context import (
    SPORT_BANNED_TERMS,
    build_programmatic_minimal_breakdown,
    safe_generate_breakdown,
    validate_sport_relevance,
    validate_sport_text,
)


class TestValidateSportText:
    def test_clean_soccer_text(self) -> None:
        text = (
            "Arsenal have kept 3 clean sheets in their last 5 matches. "
            "Their goal-scoring form has been excellent."
        )
        valid, hits = validate_sport_text(text, "soccer")
        assert valid is True
        assert hits == []

    def test_cricket_contaminated_with_soccer(self) -> None:
        text = (
            "South Africa's football prowess and their clean sheet record "
            "makes them favourites."
        )
        valid, hits = validate_sport_text(text, "cricket")
        assert valid is False
        assert "football" in hits
        assert "clean sheet" in hits

    def test_rugby_contaminated_with_cricket(self) -> None:
        text = "The Springboks' innings have been impressive, with a run rate above 6."
        valid, hits = validate_sport_text(text, "rugby")
        assert valid is False
        assert "innings" in hits
        assert "run rate" in hits

    def test_soccer_contaminated_with_rugby(self) -> None:
        text = "Liverpool's scrum-like defensive lineout structure held firm."
        valid, hits = validate_sport_text(text, "soccer")
        assert valid is False
        assert "scrum" in hits
        assert "lineout" in hits

    def test_unknown_sport_passes(self) -> None:
        text = "Anything goes for unknown sports."
        valid, hits = validate_sport_text(text, "esports")
        assert valid is True
        assert hits == []

    def test_case_insensitive(self) -> None:
        text = "The FOOTBALL match was exciting."
        valid, hits = validate_sport_text(text, "cricket")
        assert valid is False
        assert "football" in hits


class TestValidateSportRelevance:
    def test_soccer_has_relevant_terms(self) -> None:
        text = "Two goals in the first half secured the victory."
        relevant, term = validate_sport_relevance(text, "soccer")
        assert relevant is True
        assert term == "goal"

    def test_soccer_missing_relevant_terms(self) -> None:
        text = "The weather was nice and the fans were happy."
        relevant, term = validate_sport_relevance(text, "soccer")
        assert relevant is False
        assert term == ""


class TestMinimalBreakdown:
    def test_basic_fallback(self) -> None:
        result = build_programmatic_minimal_breakdown("cricket")
        assert "Cricket" in result
        assert "Limited verified data" in result
        assert "Odds-based analysis only" in result

    def test_fallback_with_summary(self) -> None:
        result = build_programmatic_minimal_breakdown("rugby", "Sharks vs Bulls, 19:00")
        assert "Sharks vs Bulls" in result


class TestSafeGenerateBreakdown:
    def test_no_data_uses_fallback(self) -> None:
        text, path = safe_generate_breakdown(
            "Some LLM text",
            "soccer",
            verified_context={"data_available": False},
        )
        assert path == "fallback_no_data"
        assert "Limited verified data" in text

    def test_banned_terms_uses_fallback(self) -> None:
        text, path = safe_generate_breakdown(
            "The football match had great innings.",
            "cricket",
            verified_context={"data_available": True},
        )
        assert path == "fallback_banned"
        assert "Limited verified data" in text

    def test_clean_text_passes(self) -> None:
        text, path = safe_generate_breakdown(
            "South Africa won the Test match with a century from the captain.",
            "cricket",
            verified_context={"data_available": True},
        )
        assert path == "enriched"
        assert "century" in text

    def test_all_five_sports_have_banned_terms(self) -> None:
        for sport in ["cricket", "rugby", "soccer", "boxing", "mma"]:
            assert sport in SPORT_BANNED_TERMS
            assert len(SPORT_BANNED_TERMS[sport]) > 0
