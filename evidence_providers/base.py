"""EvidenceProvider protocol and SportEvidence dataclass.

Every sport-specific evidence adapter implements EvidenceProvider and returns
a SportEvidence. The caller (build_evidence_pack) wraps the fetch in a 5-second
asyncio.wait_for to enforce the total budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


@dataclass
class SportEvidence:
    sport: str
    available: bool
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_name: str = ""
    stale_minutes: float = 0.0
    error: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class EvidenceProvider(Protocol):
    """Protocol that every sport-specific evidence adapter must satisfy.

    Timeout contract: callers wrap fetch_evidence in asyncio.wait_for(timeout=5.0).
    On any failure the adapter MUST return SportEvidence(available=False, error=...).
    """

    async def fetch_evidence(
        self, match_key: str, home: str, away: str, sport: str | None = None
    ) -> SportEvidence: ...

    def format_for_prompt(self, evidence: SportEvidence) -> str: ...

    def contributes_key_facts(self, evidence: SportEvidence) -> int: ...
