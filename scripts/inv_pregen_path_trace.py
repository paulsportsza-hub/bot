#!/usr/bin/env python3
"""Trace pregenerate_narratives.py render dispatch without writing cache rows."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv

    for env_path in (
        ROOT / ".env",
        Path("/home/paulsportsza/bot/.env"),
        Path("/home/paulsportsza/.env"),
    ):
        if env_path.exists():
            load_dotenv(env_path)
            break
except Exception:
    pass


def _sample(text: str | None, limit: int = 180) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _wrap_call(
    trace: list[str],
    owner: Any,
    name: str,
    label: str,
    *,
    summarise: Callable[[Any], str] | None = None,
) -> Callable[[], None]:
    original = getattr(owner, name)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        trace.append(f"CALL {label}")
        result = original(*args, **kwargs)
        if summarise is not None:
            trace.append(f"RETURN {label}: {summarise(result)}")
        return result

    setattr(owner, name, wrapper)

    def restore() -> None:
        setattr(owner, name, original)

    return restore


def _patch_attr(owner: Any, name: str, replacement: Any) -> Callable[[], None]:
    original = getattr(owner, name)
    setattr(owner, name, replacement)

    def restore() -> None:
        setattr(owner, name, original)

    return restore


def _summarise_v2_result(result: Any) -> str:
    return (
        f"valid={getattr(result, 'valid', None)} "
        f"fallback={getattr(result, 'fallback', None)} "
        f"primary_fact_type={getattr(result, 'primary_fact_type', None)} "
        f"text={_sample(getattr(result, 'text', ''))!r}"
    )


def _pick_edge(pregen: Any, match_key: str | None, limit: int) -> dict[str, Any]:
    edges = pregen._load_pregen_edges(limit=limit)
    if not edges:
        raise RuntimeError("pregen._load_pregen_edges returned no candidate edges")
    if match_key:
        for edge in edges:
            if edge.get("match_key") == match_key:
                return edge
        raise RuntimeError(f"match_key not found in pregen edge loader output: {match_key}")
    return edges[0]


async def _trace(args: argparse.Namespace) -> int:
    import card_pipeline
    import narrative_spec
    import verdict_corpus
    import verdict_engine_v2
    from scripts import pregenerate_narratives as pregen

    edge = await asyncio.to_thread(_pick_edge, pregen, args.match_key, args.limit)
    trace: list[str] = []
    store_probe: dict[str, Any] = {}
    restore_callbacks: list[Callable[[], None]] = []

    async def read_only_match_context(
        home: str,
        away: str,
        league: str,
        sport: str,
        **_: Any,
    ) -> dict[str, Any]:
        return {
            "data_available": False,
            "competition": league,
            "sport": sport,
            "home_team": {"name": home},
            "away_team": {"name": away},
        }

    def read_only_card_data(match_key: str, *_: Any, **__: Any) -> dict[str, Any]:
        return {
            "match_key": match_key,
            "data_sources_used": ["trace_stub"],
        }

    async def capture_store(
        match_id: str,
        html: str,
        tips: list[dict[str, Any]],
        edge_tier: str,
        model: str,
        **kwargs: Any,
    ) -> None:
        store_probe.update(
            {
                "match_id": match_id,
                "html": html,
                "tips_len": len(tips),
                "edge_tier": edge_tier,
                "model": model,
                **kwargs,
            }
        )

    restore_callbacks.append(
        _patch_attr(pregen, "_get_match_context", read_only_match_context)
    )
    restore_callbacks.append(
        _patch_attr(card_pipeline, "build_card_data", read_only_card_data)
    )
    restore_callbacks.append(
        _patch_attr(pregen, "_store_narrative_cache", capture_store)
    )
    restore_callbacks.append(
        _wrap_call(trace, narrative_spec, "_render_baseline", "narrative_spec._render_baseline")
    )
    restore_callbacks.append(
        _wrap_call(trace, verdict_corpus, "render_verdict", "verdict_corpus.render_verdict")
    )
    restore_callbacks.append(
        _wrap_call(
            trace,
            verdict_engine_v2,
            "render_verdict_v2",
            "verdict_engine_v2.render_verdict_v2",
            summarise=_summarise_v2_result,
        )
    )

    try:
        result = await pregen._generate_one(edge, sweep_type=args.sweep)
        cache_for_probe = dict(result.get("_cache") or {})
        if cache_for_probe:
            persist_path_accepted, persist_reason = await pregen._drift_checked_persist(cache_for_probe)
        else:
            persist_path_accepted, persist_reason = False, "no_cache_payload"
    finally:
        for restore in reversed(restore_callbacks):
            restore()

    cache = result.get("_cache") or {}
    actual_narrative_html_write = store_probe.get("html", "")

    print("## Pregen Path Trace")
    print(f"mode: {args.sweep}")
    print("dispatcher: scripts.pregenerate_narratives._generate_one")
    print(f"VERDICT_ENGINE_V2: {os.environ.get('VERDICT_ENGINE_V2', '<unset>')}")
    print(f"match_key: {edge.get('match_key', '')}")
    print(f"sport: {edge.get('sport', '')}")
    print(f"league: {edge.get('league', '')}")
    print(f"tier: {edge.get('edge_tier') or edge.get('tier') or ''}")
    print(f"best_bookmaker: {edge.get('best_bookmaker', '')}")
    print(f"best_odds: {edge.get('best_odds', '')}")
    print("side_effect_stubs: _get_match_context, card_pipeline.build_card_data, _store_narrative_cache")
    print("")
    print("## Calls")
    if trace:
        for item in trace:
            print(item)
    else:
        print("none")
    print("")
    print("## Result")
    print(f"success: {result.get('success')}")
    print(f"model: {result.get('model')}")
    print(f"narrative_len: {len(result.get('narrative') or '')}")
    print(f"cache_payload_html_len: {len(cache.get('html') or '')}")
    print(f"persist_path_accepted_before_store: {persist_path_accepted}")
    print(f"persist_path_reason: {persist_reason!r}")
    print(f"cache_write_observed: {bool(store_probe)}")
    print(f"cache_write_narrative_html_len: {len(actual_narrative_html_write)}")
    print(f"cache_write_narrative_html_repr: {actual_narrative_html_write!r}")
    print(f"cache_write_verdict_html: {_sample(store_probe.get('verdict_html'))!r}")
    print(f"cache_write_narrative_source: {store_probe.get('narrative_source')!r}")
    print(f"cache_write_engine_version: {store_probe.get('engine_version')!r}")
    print("cache_write_skipped: true (_store_narrative_cache stubbed; store validators/db writes not exercised)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Trace pregen render dispatch without cache writes")
    parser.add_argument("--sweep", default="uncached_only", choices=["full", "refresh", "uncached_only"])
    parser.add_argument("--match-key", default="manchester_city_vs_brentford_2026-05-09")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    return asyncio.run(_trace(args))


if __name__ == "__main__":
    raise SystemExit(main())
