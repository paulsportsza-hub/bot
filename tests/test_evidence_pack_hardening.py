from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.expanduser("~"))
sys.path.insert(0, os.path.join(os.path.expanduser("~"), "bot"))

from evidence_pack import (
    _add_name_variants,
    _build_simple_team_aliases,
    _display_name,
    _filter_injury_news_articles,
)


def test_injury_news_filter_rejects_unverified_player_name() -> None:
    verified: set[str] = set()
    _add_name_variants(verified, "M. Salah", min_token_len=3)
    _add_name_variants(verified, "Alisson", min_token_len=3)
    aliases = _build_simple_team_aliases("liverpool", "fulham", "Liverpool", "Fulham")

    articles = [
        {
            "title": "Ekitike, Salah and Alisson - Liverpool latest injury news after Brighton blow",
            "has_injury_mentions": True,
        },
        {
            "title": "Salah and Alisson available again for Liverpool",
            "has_injury_mentions": True,
        },
    ]

    filtered = _filter_injury_news_articles(articles, verified, aliases)

    assert [article["title"] for article in filtered] == [
        "Salah and Alisson available again for Liverpool"
    ]


def test_display_name_preserves_uppercase_suffixes() -> None:
    assert _display_name("sporting_cp") == "Sporting CP"
