"""FIX-NARRATIVE-ROT-ROOT-01 / Phase 4 / AC-4.5 — Narrative diversity monitor.

The W82-RENDER-OPENING-VARIATION instruction (Phase 4 / AC-4.4) tells the
polish prompt to vary Setup opening shape across cards. This monitor catches
drift: it samples the most-recent N narratives from `narrative_cache`,
computes the lowercase first-8-tokens of each Setup section, and emits a
`DiversityAlert` log line when any shape exceeds the 25% dominance threshold.

Usage:
    python -m scripts.monitor_narrative_diversity
    python -m scripts.monitor_narrative_diversity --n 40

The default sample size is 20 — enough to catch real drift without firing on
small-sample noise. Threshold (25%) is calibrated against the empirical 16%
baseline observed for the manager-led shape pre-Phase-4.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Iterator

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("monitor_narrative_diversity")

# Resolve the on-disk narrative DB. We replicate the bot's `_NARRATIVE_DB_PATH`
# resolution rather than importing bot.py (which initialises Sentry + Telegram
# clients). bot.py uses `_NARRATIVE_DB_PATH = str(ODDS_DB_PATH)` so we mirror
# that contract here. Falls back to the worktree's `data/odds.db` when the
# scrapers tree isn't on the filesystem (e.g. in tests).
_BOT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_CANDIDATES = (
    Path(os.environ.get("MZANSI_NARRATIVE_DB", "")),
    Path("/home/paulsportsza/scrapers/odds.db"),
    _BOT_ROOT / "data" / "odds.db",
)


def _resolve_db_path() -> Path:
    for cand in _DEFAULT_DB_CANDIDATES:
        if cand and str(cand) and Path(cand).exists():
            return Path(cand)
    # Fall back to first non-empty candidate even if missing — caller handles.
    for cand in _DEFAULT_DB_CANDIDATES:
        if cand and str(cand):
            return Path(cand)
    return _BOT_ROOT / "data" / "odds.db"


_NARRATIVE_DB_PATH = _resolve_db_path()

# 25% dominance threshold per Phase 4 / AC-4.5.
_DIVERSITY_DOMINANCE_THRESHOLD = 25.0


def first_n_tokens(text: str, n: int = 8) -> str:
    """Return the lowercase first-N tokens of the Setup section in `text`.

    Strips HTML tags before tokenising. Returns "" when no Setup section
    can be identified (e.g. cached row with malformed HTML).
    """
    if not text:
        return ""
    setup_match = re.search(r"📋[^🎯⚠️🏆]+", text)
    if not setup_match:
        return ""
    body = re.sub(r"<[^>]+>", "", setup_match.group(0)).strip()
    # Strip the literal "The Setup" header text so the 8-token sample
    # starts at the actual prose body.
    body = re.sub(r"^📋\s*The\s+Setup\s*", "", body, flags=re.IGNORECASE)
    parts = body.split()
    return " ".join(parts[:n]).lower()


def _fetch_recent_rows(
    db_path: Path | str,
    limit: int,
) -> Iterator[tuple[str, str]]:
    """Yield (match_id, narrative_html) tuples for the N most-recent rows."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "SELECT match_id, narrative_html "
            "FROM narrative_cache "
            "WHERE narrative_html IS NOT NULL "
            "AND length(trim(narrative_html)) > 0 "
            "ORDER BY created_at DESC "
            "LIMIT ?",
            (int(limit),),
        )
        for row in cur:
            yield row[0], row[1]
    finally:
        conn.close()


def analyse_diversity(
    db_path: Path | str,
    n: int,
    threshold: float = _DIVERSITY_DOMINANCE_THRESHOLD,
) -> dict:
    """Compute the dominance distribution of Setup-opening shapes.

    Returns a dict with: `total`, `shapes` (Counter), `dominant` (best shape),
    `dominant_pct` (float), `alert` (bool).
    """
    shapes: Counter[str] = Counter()
    try:
        rows = list(_fetch_recent_rows(db_path, n))
    except sqlite3.OperationalError as exc:
        # Most common: missing narrative_html column or missing table.
        # Surface the failure cleanly — graceful error per AC-4.5.
        log.warning("DiversityMonitor: DB error: %s", exc)
        return {
            "total": 0,
            "shapes": Counter(),
            "dominant": "",
            "dominant_pct": 0.0,
            "alert": False,
            "error": str(exc),
        }

    for _mid, html in rows:
        shape = first_n_tokens(html or "")
        if shape:
            shapes[shape] += 1

    total = sum(shapes.values())
    if total == 0:
        return {
            "total": 0,
            "shapes": Counter(),
            "dominant": "",
            "dominant_pct": 0.0,
            "alert": False,
        }

    dominant_shape, dominant_count = shapes.most_common(1)[0]
    dominant_pct = (dominant_count / total) * 100.0
    alert = dominant_pct > threshold
    return {
        "total": total,
        "shapes": shapes,
        "dominant": dominant_shape,
        "dominant_pct": dominant_pct,
        "alert": alert,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n", type=int, default=20,
        help="Sample size — number of recent narrative_cache rows to scan.",
    )
    parser.add_argument(
        "--threshold", type=float,
        default=_DIVERSITY_DOMINANCE_THRESHOLD,
        help="Dominance percentage above which to emit a DiversityAlert.",
    )
    parser.add_argument(
        "--db", type=str, default=None,
        help="Override the narrative DB path (defaults to bot's path).",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db) if args.db else _NARRATIVE_DB_PATH
    result = analyse_diversity(db_path, args.n, threshold=args.threshold)

    if result.get("error"):
        # Already logged in analyse_diversity; exit clean (graceful).
        return 0
    total = result["total"]
    if total == 0:
        log.info("DiversityMonitor: empty sample — no narrative_cache rows.")
        return 0

    for shape, count in result["shapes"].most_common():
        pct = (count / total) * 100.0
        if pct > args.threshold:
            print(
                "FIX-NARRATIVE-ROT-ROOT-01 DiversityAlert "
                f"match_count={total} dominant_shape={shape!r} pct={pct:.1f}"
            )
        elif pct >= 5.0:
            log.info(
                "DiversityMonitor: shape=%r count=%d pct=%.1f",
                shape, count, pct,
            )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
