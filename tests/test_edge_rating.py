from __future__ import annotations

from services.edge_rating import EdgeRating, calculate_edge_rating, calculate_edge_score


def test_diamond_requires_line_movement_data() -> None:
    snapshots = [
        {"bookmaker": f"bk{i}", "outcome": "home", "odds": odds}
        for i, odds in enumerate([1.2, 1.25, 1.3, 1.35, 2.2])
    ]
    snapshots += [
        {"bookmaker": f"bk{i}", "outcome": "away", "odds": odds}
        for i, odds in enumerate([4.4, 4.2, 4.1, 4.0, 3.9])
    ]

    model = {"outcome": "home", "confidence": 0.8, "implied_prob": 0.65}

    score = calculate_edge_score(snapshots, model, line_movement=None)
    rating = calculate_edge_rating(snapshots, model, line_movement=None)

    assert score < 85
    assert rating == EdgeRating.GOLD


def test_diamond_requires_multi_outcome_market_data() -> None:
    snapshots = [
        {"bookmaker": f"bk{i}", "outcome": "home", "odds": odds}
        for i, odds in enumerate([1.35, 1.4, 1.45, 1.45, 1.6])
    ]
    model = {"outcome": "home", "confidence": 0.95, "implied_prob": 0.72}
    movement = {"direction": "shortening", "magnitude": 0.1, "hours": 24}

    score = calculate_edge_score(snapshots, model, movement)
    rating = calculate_edge_rating(snapshots, model, movement)

    assert score < 85
    assert rating == EdgeRating.GOLD


def test_complete_data_can_still_reach_diamond() -> None:
    snapshots = [
        {"bookmaker": f"bk{i}", "outcome": "home", "odds": odds}
        for i, odds in enumerate([1.35, 1.4, 1.45, 1.45, 1.6])
    ]
    snapshots += [
        {"bookmaker": f"bk{i}", "outcome": "away", "odds": odds}
        for i, odds in enumerate([4.8, 4.6, 4.5, 4.4, 4.2])
    ]
    model = {"outcome": "home", "confidence": 0.95, "implied_prob": 0.72}
    movement = {"direction": "shortening", "magnitude": 0.1, "hours": 24}

    score = calculate_edge_score(snapshots, model, movement)
    rating = calculate_edge_rating(snapshots, model, movement)

    assert score >= 85
    assert rating == EdgeRating.DIAMOND
