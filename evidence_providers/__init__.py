"""Sport-specific evidence provider registry.

Usage:
    from evidence_providers import get_sport_provider
    provider = get_sport_provider("cricket")
    if provider:
        evidence = await asyncio.wait_for(
            provider.fetch_evidence(match_key, home, away), timeout=5.0
        )
"""

from __future__ import annotations

from evidence_providers.base import EvidenceProvider, SportEvidence
from evidence_providers.combat_evidence import CombatEvidenceProvider
from evidence_providers.cricket_evidence import CricketEvidenceProvider
from evidence_providers.rate_monitor import RateMonitor
from evidence_providers.rugby_evidence import RugbyEvidenceProvider

# Global rate monitor singleton — all providers share this instance.
rate_monitor = RateMonitor()
rate_monitor.register_provider("cricketdata", daily_limit=100)
rate_monitor.register_provider("api_sports", daily_limit=100, shared_with=["rugby", "mma"])
rate_monitor.register_provider("boxing_data", daily_limit=100)

__all__ = ["EvidenceProvider", "SportEvidence", "CombatEvidenceProvider", "get_sport_provider"]

_SPORT_EVIDENCE_PROVIDERS: dict[str, EvidenceProvider] = {
    "cricket": CricketEvidenceProvider(),  # type: ignore[assignment]
    "rugby": RugbyEvidenceProvider(),  # type: ignore[assignment]
    "mma": CombatEvidenceProvider(),  # type: ignore[assignment]
    "boxing": CombatEvidenceProvider(),  # type: ignore[assignment]
    "combat": CombatEvidenceProvider(),  # type: ignore[assignment]
}


def get_sport_provider(sport: str) -> EvidenceProvider | None:
    """Return the evidence provider for *sport*, or None if none is registered.

    Soccer returns None intentionally — football evidence stays on its existing path.
    """
    return _SPORT_EVIDENCE_PROVIDERS.get(sport.lower())
