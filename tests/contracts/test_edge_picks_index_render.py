from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

from card_data import build_edge_picks_index_data
from card_renderer import render_card_sync


REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_DIR = REPO_ROOT / "static" / "qa-gallery" / "canonical"
COUNTS = {"diamond": 1, "gold": 7, "silver": 13, "bronze": 5}


def _render_index(user_tier: str, counts: dict[str, int]) -> Image.Image:
    data = build_edge_picks_index_data(user_tier, counts)
    png = render_card_sync("edge_picks_index.html", data, width=480)
    return Image.open(io.BytesIO(png)).convert("RGB")


def _canonical(name: str) -> Image.Image:
    return Image.open(CANONICAL_DIR / f"edge_picks_index_{name}.png").convert("RGB")


@pytest.mark.parametrize(
    ("scenario", "user_tier", "counts"),
    [
        ("bronze", "bronze", COUNTS),
        ("silver", "silver", COUNTS),
        ("gold", "gold", COUNTS),
        ("diamond", "diamond", COUNTS),
        ("empty", "bronze", {"diamond": 0, "gold": 0, "silver": 0, "bronze": 0}),
    ],
)
def test_edge_picks_index_render_matches_canonical_pixels(
    scenario: str,
    user_tier: str,
    counts: dict[str, int],
) -> None:
    rendered = _render_index(user_tier, counts)
    expected = _canonical(scenario)

    assert rendered.size == expected.size
    diff = ImageChops.difference(rendered, expected)
    stat = ImageStat.Stat(diff)
    mean_delta = sum(stat.mean) / len(stat.mean)
    max_delta = max(channel[1] for channel in diff.getextrema())

    assert mean_delta <= 1.0
    assert max_delta <= 40
