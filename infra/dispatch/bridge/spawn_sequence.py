"""Spawn sequence driver — drives a CMUX surface through mosh → claude → prompt.

Two implementations are defined:

  MultiStepSpawn (PRIMARY)
    Documented multi-step sequence with sleeps.  Always available.

  InlineSpawn (INACTIVE)
    Single-line send via hypothetical --trust + --prompt flags.
    Phase-0 finding: neither flag exists in the current claude CLI.
    Activate by setting USE_INLINE_SPAWN=1 when/if claude gains these flags.

Phase-0 summary (probed 2026-04-30 on server):
  • claude --trust / --no-trust-prompt: NOT present in `claude --help`.
  • Positional prompt arg works only with -p/--print (non-interactive).
  • claude --model <model> and --effort max: AVAILABLE.
  → MultiStepSpawn is mandatory; InlineSpawn kept as a future activation stub.
"""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import logging
import os
import re
import secrets
import shlex
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


log = logging.getLogger(__name__)

_SERVER_DEFAULT = "paulsportsza@37.27.179.53"

# AC-4 — step 0 + 2.5 prompt-return marker wait.
# Replaces fixed asyncio.sleep() with a unique-marker echo + poll. Kills the
# race where a large base64 dispatch.md write was still echoing when the
# next command (`codex --profile high`) was injected, producing the
# `SEMAPHORcodex --profile high` corruption observed 2026-05-02.
_PROMPT_WAIT_POLL_S: float = 0.2
_PROMPT_WAIT_TIMEOUT_S: float = 60.0

MODEL_COMMANDS = {
    "sonnet": ["claude", "--model", "sonnet"],
    "opus-max": ["claude", "--model", "opus", "--effort", "max"],
    "codex-medium": ["codex", "--profile", "medium"],
    "codex-high": ["codex", "--profile", "high"],
    "codex-xhigh": ["codex", "--profile", "xhigh"],
}

TASK_SIGNATURES = [
    {
        "name": "payments_auth_settlement",
        "matches": {
            "paths": ["*stitch*", "*payment*", "*subscription*", "*checkout*", "*auth*", "*settlement*"],
            "risk_tags": ["money", "auth", "settlement"],
            "brief_terms": ["payment", "checkout", "billing", "auth", "refund"],
        },
        "executor": "codex-xhigh",
        "reviewer": "opus-max",
        "review_mode": "adversarial",
        "mechanism": "subprocess",
        "boundary_score": 1000,
        "reason": "irreversible value or identity boundary (mandatory adversarial)",
    },
    {
        "name": "alerts_dm_fanout",
        "matches": {
            "risk_tags": ["fanout", "claim-before-send"],
            "brief_terms": ["alert", "dm", "double-post", "notification", "fanout", "publish-batch"],
        },
        "executor": "codex-xhigh",
        "reviewer": "opus-max",
        "review_mode": "adversarial",
        "mechanism": "subprocess",
        "boundary_score": 1000,
        "reason": "fanout boundary (mandatory adversarial per FIX-ALERTS-DOUBLE-POST-DEDUP-01)",
    },
    {
        "name": "dispatch_governance_state",
        "matches": {
            "repos": ["dispatch"],
            "paths": ["dispatch_promoter.py", "enqueue.py", "cmux_bridge/*.py", "mark_done.sh", "spawn_sequence.py"],
            "risk_tags": ["dispatch-state", "review-gate"],
        },
        "executor": "codex-xhigh",
        "reviewer": "opus-max",
        "review_mode": "adversarial",
        "mechanism": "subprocess",
        "boundary_score": 1000,
        "reason": "dispatch-governance boundary - process bugs make future governance lie",
    },
    {
        "name": "non_rollback_migration",
        "matches": {
            "risk_tags": ["migration", "schema-change", "backfill"],
            "brief_terms": ["migration", "backfill", "schema"],
        },
        "executor": "codex-xhigh",
        "reviewer": "opus-max",
        "review_mode": "adversarial",
        "mechanism": "subprocess",
        "boundary_score": 1000,
        "reason": "persistent production-data boundary",
    },
    {
        "name": "runtime_concurrency_cache",
        "matches": {
            "paths": ["bot.py", "card_sender.py", "scripts/pregenerate_narratives.py"],
            "brief_terms": ["cache", "async", "lock", "timeout", "dedupe", "claim", "race"],
            "risk_tags": ["concurrency", "cache"],
        },
        "executor": "codex-xhigh",
        "reviewer": "opus-max",
        "review_mode": "review",
        "mechanism": "subprocess",
        "reason": "runtime concurrency/cache class - recent incident density",
    },
    {
        "name": "premium_narrative_cache",
        "matches": {
            "paths": ["narrative_*.py", "evidence_pack.py", "pregenerate_narratives.py", "card_data.py"],
            "brief_terms": ["narrative", "verdict", "premium", "pregen", "quality gate"],
            "risk_tags": ["premium-narrative"],
        },
        "executor": "codex-xhigh",
        "reviewer": "opus-max",
        "review_mode": "review",
        "mechanism": "cowork-queue",
        "reason": "premium trust boundary - Cowork queue review for context",
    },
    {
        "name": "grep_trace_call_site",
        "matches": {
            "klass": ["INV", "QA"],
            "brief_terms": ["call site", "grep", "audit", "contract", "harness", "parser"],
        },
        "executor": "codex-xhigh",
        "reviewer": "sonnet",
        "review_mode": "review",
        "mechanism": "subprocess",
        "reason": "code archaeology - Codex strong, Sonnet review sufficient",
    },
    {
        "name": "judgement_launch_narrative",
        "matches": {
            "klass": ["INV", "QA", "NARRATIVE"],
            "brief_terms": ["launch", "premium", "narrative quality", "no-go", "calibration", "brand", "doctrine"],
        },
        "executor": "opus-max",
        "reviewer": "codex-xhigh",
        "review_mode": "review",
        "mechanism": "cowork-queue",
        "reason": "Opus judgement domain - Cowork queue review",
    },
    {
        "name": "bounded_fix_routine",
        "matches": {
            "klass": ["FIX"],
            "prod_file_count_lte": 3,
            "risk_tags_absent": ["money", "auth", "migration", "fanout", "dispatch-state", "premium-narrative"],
        },
        "executor": "sonnet",
        "reviewer": "codex-medium",
        "review_mode": "review",
        "mechanism": "subprocess",
        "reason": "Sonnet high-volume routine + cheapest competent reviewer",
    },
    {
        "name": "trivial_mechanical",
        "matches": {
            "klass": ["FIX-S", "DOCS", "OPS"],
            "prod_file_count_lte": 1,
            "brief_terms": ["typo", "rename", "anchor", "mirror sync"],
        },
        "executor": "codex-medium",
        "reviewer": "sonnet",
        "review_mode": "review",
        "mechanism": "subprocess",
        "reason": "trivial mechanical - cheapest Codex tier suffices",
    },
    {
        "name": "docs_routine",
        "matches": {
            "klass": ["DOCS", "OPS"],
            "prod_file_count_lte": 3,
            "risk_tags_absent": ["dispatch-state", "review-gate", "doctrine"],
        },
        "executor": "sonnet",
        "reviewer": "codex-medium",
        "review_mode": "review",
        "mechanism": "subprocess",
        "reason": "routine docs/ops - cheap rotation",
    },
    {
        "name": "content_low_stakes",
        "matches": {
            "klass": ["CONTENT"],
            "risk_tags_absent": ["premium", "responsible-gambling", "launch"],
        },
        "executor": "sonnet",
        "reviewer": "codex-medium",
        "review_mode": "review",
        "mechanism": "subprocess",
        "reason": "routine content",
    },
    {
        "name": "content_premium",
        "matches": {
            "klass": ["CONTENT"],
            "risk_tags": ["premium", "responsible-gambling", "launch"],
        },
        "executor": "opus-max",
        "reviewer": "codex-high",
        "review_mode": "review",
        "mechanism": "cowork-queue",
        "reason": "premium content - Opus voice + Cowork brand context review",
    },
]


@dataclass(frozen=True)
class BriefExecutionMeta:
    brief_id: str
    klass: str
    target_repo: str
    agent: str
    files: tuple[str, ...] = ()
    risk_tags: tuple[str, ...] = ()
    review_mode: str = "review"
    title: str = ""
    declared_model_override: str | None = None


@dataclass(frozen=True)
class Route:
    executor_cmd: list[str]
    reviewer: str
    review_mode: Literal["review", "adversarial"]
    mechanism: Literal["subprocess", "cowork-queue"]
    rationale: str


class SpawnTimeoutError(RuntimeError):
    """Raised when a spawn marker is not observed before timeout."""


def _split_marker_for_shell(marker: str) -> str:
    """Emit marker without typing the contiguous marker into the terminal."""
    half = len(marker) // 2
    a, b = marker[:half], marker[half:]
    return f'printf "%s%s\\n" "{a}" "{b}"'

# Model Routing v1 (LOCKED 2 May 2026 PM, supersedes Codex-only cutover):
# map Agent string substring → full executor command parts (binary + flags).
# Both Codex and Claude are supported executors per Routing v1.
# Canonical: ops/MODEL-ROUTING.md.
#
# Codex profiles live in ~/.codex/config.toml on the server:
#   [profiles.xhigh]   model="gpt-5.5"  model_reasoning_effort="xhigh"
#   [profiles.high]    model="gpt-5.5"  model_reasoning_effort="high"
#   [profiles.medium]  model="gpt-5.5"  model_reasoning_effort="medium"
#
# Active Agent-select options on Briefs DB / Pipeline DS (16 total):
#   "Codex XHigh - <ROLE>"       → codex --profile xhigh
#   "Codex High  - <ROLE>"       → codex --profile high
#   "Opus Max Effort - <ROLE>"   → claude --model opus --effort max
#   "Sonnet      - <ROLE>"       → claude --model sonnet
#
# Order of evaluation MATTERS: "codex xhigh" before "xhigh" (legacy);
# "codex high" before plain "high"; "xhigh" (legacy) before "high"
# because "xhigh" contains "high".
_MODEL_KEYWORDS: list[tuple[str, list[str]]] = [
    # --- Routing v1 canonical options (16 active) ---
    ("codex xhigh",      ["codex", "--profile", "xhigh"]),
    ("codex high",       ["codex", "--profile", "high"]),
    ("opus max effort",  ["claude", "--model", "opus", "--effort", "max"]),
    ("sonnet",           ["claude", "--model", "sonnet"]),
    # --- Legacy options (transitional, retained for in-flight briefs) ---
    # Codex-cutover-era (1 May 2026 PM): "XHigh / High / Medium - <ROLE>".
    ("xhigh",  ["codex", "--profile", "xhigh"]),
    ("medium", ["codex", "--profile", "medium"]),
    ("high",   ["codex", "--profile", "high"]),
    # Pre-cutover Claude legacy: plain "Opus - <ROLE>".
    ("opus",   ["claude", "--model", "opus"]),
]


def _model_flags(agent: str) -> list[str]:
    """Return [binary, *flags] for this Agent string. Routing v1.

    DISPATCH_MODE=pure-codex overrides the agent field entirely and always
    returns ``codex --profile xhigh``, regardless of what the brief declared.
    Activate by setting DISPATCH_MODE=pure-codex in the bridge plist
    EnvironmentVariables and running ``launchctl kickstart``.  See SO #44
    and ops/MODEL-ROUTING.md §5.

    Raises on empty / unknown agent — never silent-default."""
    # pure-codex mode: DISPATCH_MODE env overrides agent field completely.
    if os.environ.get("DISPATCH_MODE") == "pure-codex":
        log.debug(
            "spawn_sequence: DISPATCH_MODE=pure-codex — forcing "
            "codex xhigh (agent=%r ignored)",
            agent,
        )
        return ["codex", "--profile", "xhigh"]
    if not agent or not agent.strip():
        # Fail loud — refuse to silently default when the brief's Agent
        # field is empty. The original leak (29-30 Apr 2026) shipped
        # mis-tagged work because this branch fell through to a default.
        raise ValueError(
            "spawn_sequence: brief has empty agent — refusing to default. "
            "Fix the upstream brief (Notion Agent select + enqueue.py "
            "guard) before retrying."
        )
    # Strip "(legacy)" suffix so e.g. "Sonnet - LEAD (legacy)" still
    # resolves to the same command as "Sonnet - LEAD".
    low = agent.lower().replace("(legacy)", "").strip()
    for keyword, parts in _MODEL_KEYWORDS:
        if keyword in low:
            return parts
    raise ValueError(
        f"spawn_sequence: brief agent={agent!r} matches no known model "
        f"keyword (codex xhigh / codex high / opus max effort / "
        f"sonnet / xhigh / high / medium / opus). Refusing to "
        f"silent-default."
    )


def _normalise_tuple(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        raw_items = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]
    items: list[str] = []
    for item in raw_items:
        cleaned = str(item).strip().lstrip("-").strip()
        if cleaned:
            items.append(cleaned)
    return tuple(items)


def _klass_from_brief_id(brief_id: str) -> str:
    if not brief_id:
        return ""
    prefix = brief_id.split("-", 1)[0].upper()
    return prefix.rstrip()


def _normalise_review_mode(value: str) -> str:
    low = value.lower().strip()
    if low in {"adversarial", "adversarial-review"}:
        return "adversarial"
    return "review"


def _brief_execution_meta_from_data(brief_data: dict[str, Any]) -> BriefExecutionMeta:
    raw_meta = brief_data.get("meta")
    meta_data = raw_meta if isinstance(raw_meta, dict) else {}

    def has_value(value: Any) -> bool:
        if value is None or value == "":
            return False
        if isinstance(value, (dict, list, tuple, set)) and not value:
            return False
        return True

    def pick(*keys: str, default: Any = "") -> Any:
        for source in (meta_data, brief_data):
            for key in keys:
                value = source.get(key)
                if has_value(value):
                    return value
        return default

    brief_id = str(pick("brief_id", "id", default="UNKNOWN"))
    klass = str(pick("klass", "class")).upper()
    if not klass:
        klass = _klass_from_brief_id(brief_id)
    return BriefExecutionMeta(
        brief_id=brief_id,
        klass=klass,
        target_repo=str(pick("target_repo", "repo")),
        agent=str(pick("agent")),
        files=_normalise_tuple(pick("files", "files_in_scope", default=())),
        risk_tags=_normalise_tuple(pick("risk_tags", "risk", default=())),
        review_mode=str(pick("review_mode", default="review")),
        title=str(pick("title", "brief")),
        declared_model_override=(
            str(
                pick("declared_model_override", "model_override")
            ).strip()
            or None
        ),
    )


def _klass_matches(actual: str, expected: str, brief_id: str) -> bool:
    actual = (actual or _klass_from_brief_id(brief_id)).upper()
    expected = expected.upper()
    if expected == "FIX":
        return actual == "FIX" or actual.startswith("FIX-") or brief_id.upper().startswith("FIX-")
    return actual == expected


def _brief_text(meta: BriefExecutionMeta) -> str:
    return f"{meta.brief_id} {meta.title}".lower().replace("_", "-")


def _term_matches(meta: BriefExecutionMeta, term: str) -> bool:
    text = _brief_text(meta)
    spaced = text.replace("-", " ")
    needle = term.lower()
    return needle in text or needle.replace("-", " ") in spaced


def _path_matches(path: str, pattern: str) -> bool:
    clean_path = str(path).strip().lower().replace("\\", "/")
    clean_path = clean_path.split(" ", 1)[0].lstrip("./")
    clean_pattern = pattern.lower().replace("\\", "/")
    basename = clean_path.rsplit("/", 1)[-1]
    return (
        fnmatch.fnmatch(clean_path, clean_pattern)
        or fnmatch.fnmatch(basename, clean_pattern)
        or fnmatch.fnmatch(clean_path, f"*/{clean_pattern}")
    )


def _is_production_file(path: str) -> bool:
    clean_path = str(path).strip().lower().replace("\\", "/")
    clean_path = clean_path.split(" ", 1)[0].lstrip("./")
    if not clean_path:
        return False
    if clean_path.startswith("tests/") or "/tests/" in clean_path:
        return False
    basename = clean_path.rsplit("/", 1)[-1]
    if basename.startswith("test_") or basename.endswith("_test.py"):
        return False
    if clean_path.endswith((".md", ".markdown", ".rst", ".txt")):
        return False
    return True


def _production_file_count(meta: BriefExecutionMeta) -> int:
    return sum(1 for path in meta.files if _is_production_file(path))


def signature_score(signature: dict[str, Any], meta: BriefExecutionMeta) -> int:
    matches = signature.get("matches", {})
    if not isinstance(matches, dict):
        return 0

    prod_limit = matches.get("prod_file_count_lte")
    if prod_limit is not None and _production_file_count(meta) > int(prod_limit):
        return 0

    risk_tags = {tag.lower() for tag in meta.risk_tags}
    absent = {str(tag).lower() for tag in matches.get("risk_tags_absent", [])}
    if absent & risk_tags:
        return 0

    score = 0
    nonklass_score = 0

    klasses = matches.get("klass", [])
    if klasses and any(_klass_matches(meta.klass, str(klass), meta.brief_id) for klass in klasses):
        score += 15

    repos = {str(repo).lower() for repo in matches.get("repos", [])}
    if repos and meta.target_repo.lower() in repos:
        score += 25
        nonklass_score += 25

    paths = matches.get("paths", [])
    if paths and any(_path_matches(path, str(pattern)) for path in meta.files for pattern in paths):
        score += 35
        nonklass_score += 35

    terms = matches.get("brief_terms", [])
    if terms and any(_term_matches(meta, str(term)) for term in terms):
        score += 40
        nonklass_score += 40

    expected_risks = {str(tag).lower() for tag in matches.get("risk_tags", [])}
    if expected_risks and expected_risks & risk_tags:
        score += 100
        nonklass_score += 100

    class_only_signature = (
        terms
        and nonklass_score == 0
        and "risk_tags_absent" not in matches
        and "prod_file_count_lte" not in matches
    )
    if class_only_signature:
        return 0
    return score


def _route_for_models(
    executor: str,
    reviewer: str,
    *,
    review_mode: str = "review",
    mechanism: str = "subprocess",
    rationale: str,
) -> Route:
    return Route(
        executor_cmd=list(MODEL_COMMANDS[executor]),
        reviewer=reviewer,
        review_mode=_normalise_review_mode(review_mode),  # type: ignore[arg-type]
        mechanism=mechanism,  # type: ignore[arg-type]
        rationale=rationale,
    )


def _class_default_route(meta: BriefExecutionMeta) -> Route:
    klass = (meta.klass or _klass_from_brief_id(meta.brief_id)).upper()
    prod_count = _production_file_count(meta)
    if klass.startswith("FIX"):
        if prod_count > 3:
            return _route_for_models(
                "codex-xhigh",
                "opus-max",
                review_mode=meta.review_mode,
                rationale="class default: FIX-L",
            )
        reviewer = "codex-medium" if prod_count <= 1 else "codex-high"
        return _route_for_models(
            "sonnet",
            reviewer,
            review_mode=meta.review_mode,
            rationale=f"class default: FIX with {prod_count} production files",
        )
    if klass == "BUILD":
        return _route_for_models(
            "sonnet",
            "codex-high",
            review_mode=meta.review_mode,
            rationale="class default: BUILD bounded scope",
        )
    if klass == "QA":
        return _route_for_models(
            "codex-xhigh",
            "sonnet",
            review_mode=meta.review_mode,
            rationale="class default: QA mechanical harness/visual diff",
        )
    if klass == "NARRATIVE":
        return _route_for_models(
            "codex-xhigh",
            "opus-max",
            review_mode=meta.review_mode,
            rationale="class default: NARRATIVE validator/prompt edits",
        )
    if klass in {"OPS", "DOCS", "CONTENT", "INV"}:
        return _route_for_models(
            "sonnet",
            "codex-medium",
            review_mode=meta.review_mode,
            rationale=f"class default: {klass or 'unknown'}",
        )
    return _route_for_models(
        "sonnet",
        "codex-medium",
        review_mode=meta.review_mode,
        rationale="class default: unknown metadata",
    )


def _model_key_from_override(value: str) -> str | None:
    low = value.lower().replace("_", "-").strip()
    if low in MODEL_COMMANDS:
        return low
    if "opus" in low and "max" in low:
        return "opus-max"
    if "sonnet" in low:
        return "sonnet"
    if "codex" in low and "medium" in low:
        return "codex-medium"
    if "codex" in low and "xhigh" in low:
        return "codex-xhigh"
    if "codex" in low and "high" in low:
        return "codex-high"
    return None


def _route_from_override(meta: BriefExecutionMeta) -> Route | None:
    if not meta.declared_model_override:
        return None
    executor = _model_key_from_override(meta.declared_model_override)
    if executor is None:
        log.warning(
            "full-stack declared_model_override=%r did not map to MODEL_COMMANDS",
            meta.declared_model_override,
        )
        return None
    default = _class_default_route(meta)
    return _route_for_models(
        executor,
        default.reviewer,
        review_mode=default.review_mode,
        mechanism=default.mechanism,
        rationale=f"declared model override: {meta.declared_model_override}",
    )


def _route_from_signature(signature: dict[str, Any], meta: BriefExecutionMeta) -> Route:
    return _route_for_models(
        str(signature["executor"]),
        str(signature["reviewer"]),
        review_mode=str(signature.get("review_mode", meta.review_mode)),
        mechanism=str(signature.get("mechanism", "subprocess")),
        rationale=f"{signature.get('name')}: {signature.get('reason', '')}",
    )


def _ambiguous_route(meta: BriefExecutionMeta, signatures: list[dict[str, Any]]) -> Route:
    mandatory = [sig for sig in signatures if int(sig.get("boundary_score", 0) or 0) > 0]
    if len(mandatory) == 1:
        chosen = mandatory[0]
    else:
        chosen = next(
            (sig for sig in signatures if sig.get("executor") == "codex-xhigh"),
            signatures[0],
        )
    log.warning(
        "full-stack route ambiguity brief=%s candidates=%s chosen=%s",
        meta.brief_id,
        [sig.get("name") for sig in signatures],
        chosen.get("name"),
    )
    return _route_from_signature(chosen, meta)


def resolve_full_stack_route(meta: BriefExecutionMeta) -> Route:
    override = _route_from_override(meta)
    if override is not None:
        return override

    matches: list[tuple[int, dict[str, Any]]] = []
    for signature in TASK_SIGNATURES:
        score = signature_score(signature, meta)
        if score > 0:
            matches.append((score + int(signature.get("boundary_score", 0) or 0), signature))

    if not matches:
        return _class_default_route(meta)

    matches.sort(key=lambda item: item[0], reverse=True)
    if len(matches) >= 2 and matches[0][0] == matches[1][0]:
        return _ambiguous_route(meta, [item[1] for item in matches if item[0] == matches[0][0]])

    return _route_from_signature(matches[0][1], meta)


def _agent_cmd(agent: str, meta: BriefExecutionMeta | None = None) -> str:
    """Build the executor CLI command for this brief's Agent select.

    Returns a shell-ready command string like 'codex --profile xhigh' or
    'claude --model sonnet'. Routing v1 dispatches to either codex or
    claude depending on the agent string."""
    mode = os.environ.get("DISPATCH_MODE", "hybrid").lower()
    if mode == "pure-codex":
        return shlex.join(MODEL_COMMANDS["codex-xhigh"])
    if mode == "full-stack":
        if meta is None:
            log.warning("full-stack with missing meta - falling back to hybrid")
            return shlex.join(_model_flags(agent))
        route = resolve_full_stack_route(meta)
        log.info("full_stack_route=%s", route)
        return shlex.join(route.executor_cmd)
    if meta is not None:
        route = resolve_full_stack_route(meta)
        log.info("shadow_route=%s actual_agent=%r", route, agent)
    return shlex.join(_model_flags(agent))


# Backwards-compat alias — older code in this module called _claude_cmd.
# Misleading post-Routing-v1 (it now returns codex commands too) but kept
# until all callers migrate. Will be deleted in a follow-up cleanup.
_claude_cmd = _agent_cmd


async def _wait_for_marker(
    surface_id: str,
    cmux: Any,
    marker: str,
    *,
    timeout_s: float = _PROMPT_WAIT_TIMEOUT_S,
    poll_s: float = _PROMPT_WAIT_POLL_S,
) -> bool:
    """Poll the surface buffer until ``marker`` appears (echoed back by the
    remote shell) or ``timeout_s`` elapses.

    Returns True on hit. Raises on timeout so the caller cannot proceed to
    the next spawn step while a large payload is still echoing.
    """
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_buf = ""
    last_non_string_type: str | None = None
    while True:
        try:
            raw = cmux.surface_read_text(surface_id)
        except Exception as exc:  # noqa: BLE001 — defensive, log + retry
            log.warning("prompt-wait read failed (surface=%s): %s", surface_id, exc)
            raw = ""

        if isinstance(raw, str):
            last_buf = raw
            last_non_string_type = None
            if marker in raw:
                return True
        else:
            non_string_type = type(raw).__name__
            if non_string_type != last_non_string_type:
                log.warning(
                    "prompt-wait surface=%s returned non-string buffer (%s); retrying",
                    surface_id, non_string_type,
                )
                last_non_string_type = non_string_type

        if asyncio.get_event_loop().time() >= deadline:
            tail = last_buf[-500:] if isinstance(last_buf, str) else ""
            raise SpawnTimeoutError(
                f"marker {marker!r} not seen on surface={surface_id} within "
                f"{timeout_s:.1f}s; last_non_string={last_non_string_type}; "
                f"buffer_tail={tail!r}"
            )
        await asyncio.sleep(poll_s)


def _local_cd_command(brief_id: str) -> str:
    """Build a local-shell command that cd's into a brief-named scratch dir.

    CMUX renders the workspace's second-line subtitle from the LOCAL bash's
    cwd (reported via OSC 7 on each prompt). By cd'ing the local shell into
    `/tmp/_briefs/<BRIEF-ID>` BEFORE mosh runs, the subtitle becomes the
    brief id and stays put for the life of the workspace (mosh is a
    foreground process — local cwd doesn't change while it runs, and
    sticks when it exits).

    The dir is created if missing; ignored if it already exists.
    Path is /tmp so it's auto-cleaned at boot, no maintenance needed.
    """
    return f"mkdir -p /tmp/_briefs/{brief_id} && cd /tmp/_briefs/{brief_id}"


def _build_dispatch_block(brief_data: dict[str, Any]) -> str:
    brief_id = brief_data.get("brief_id", "UNKNOWN")
    notion_url = brief_data.get("notion_url", "")
    date = str(brief_data.get("enqueued_at", ""))[:10]
    notion_token = "$NOTION_TOKEN"
    return (
        f"{brief_id} — {date}\n"
        f"{notion_url}\n"
        f"NOTION_TOKEN: {notion_token}\n"
        "Execute this brief.\n"
        "\n"
        "When you finish (after filing the Notion report per SO #35), "
        "close the dispatch loop by running this single command, "
        "substituting the actual Notion report URL you just filed:\n"
        f"  bash /home/paulsportsza/dispatch/mark_done.sh {brief_id} \"<REPORT-NOTION-URL>\"\n"
        "This moves the brief into done/ and triggers the workspace tick rename."
    )


def _route_field(brief_data: dict[str, Any], key: str) -> str:
    """Return a route field from dict/object route metadata if present."""
    route = brief_data.get("route") or brief_data.get("Route") or {}
    value: Any = None
    if isinstance(route, dict):
        value = route.get(key) or route.get(key.replace("_", "-"))
    else:
        value = getattr(route, key, None)
    if value in (None, ""):
        value = brief_data.get(key) or brief_data.get(f"route_{key}")
    return str(value or "").strip()


def _normalise_review_gate_mode(value: str) -> str:
    low = value.lower().strip()
    if low in {"adversarial", "adversarial-review"}:
        return "adversarial"
    return "standard"


def _claude_reviewer_config(reviewer: str) -> tuple[str, str] | None:
    low = reviewer.lower().strip()
    if low in {"sonnet", "claude-sonnet"} or low.startswith("sonnet-"):
        return "sonnet", "standard"
    if low in {"opus", "opus-max", "opus-max-effort", "claude-opus"} or low.startswith("opus-"):
        return "opus", "max"
    if not low.startswith("claude-"):
        return None
    model = "sonnet" if "sonnet" in low else "opus"
    if "standard" in low:
        effort = "standard"
    elif "max" in low or model == "opus":
        effort = "max"
    else:
        effort = "standard"
    return model, effort


def _safe_review_path_id(brief_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", brief_id) or "UNKNOWN"


def _claude_review_gate_instruction(
    brief_id: str,
    *,
    reviewer: str,
    review_mode: str,
) -> str:
    config = _claude_reviewer_config(reviewer)
    if config is None:
        raise ValueError(f"reviewer is not Claude-routable: {reviewer!r}")
    model, effort = config
    safe_id = _safe_review_path_id(brief_id)
    command = (
        f"mkdir -p /tmp/_reviews/{safe_id}; "
        f"python3 /home/paulsportsza/dispatch/claude_review.py "
        f"--brief-id {shlex.quote(brief_id)} "
        f"--model {model} "
        f"--effort {effort} "
        f"--review-mode {review_mode} "
        f"--diff-base origin/main "
        f"--diff-head HEAD "
        f"--output-path /tmp/_reviews/{safe_id}/$(git rev-parse --short=12 HEAD)-claude-review.md"
    )
    return (
        "SO #45 REVIEW GATE (Claude reviewer subprocess): after commit + push, "
        f"before mark_done.sh, run `{command}`. "
        "Embed the wrapper output verbatim under `## Cross-Model Review` in the "
        "completion report. If it exits 1, address findings and rerun; if it "
        "exits 2, report the gate error and do not mark done."
    )


def _codex_profile_for_reviewer(reviewer: str) -> str:
    low = reviewer.lower().replace("_", "-").strip()
    if "medium" in low:
        return "medium"
    if "xhigh" in low:
        return "xhigh"
    if "high" in low:
        return "high"
    return "xhigh"


def _codex_review_gate_instruction(dispatch_file: str, *, reviewer: str = "codex-xhigh") -> str:
    profile = _codex_profile_for_reviewer(reviewer)
    return (
        "SO #45 REVIEW GATE (Codex reviewer subprocess): after commit + push, "
        "before mark_done.sh, run a fresh inline Codex sub-agent review with "
        f"`DIFF=$(git show --stat --patch HEAD); codex --profile {profile} exec "
        "\"You are an INDEPENDENT reviewer with NO prior context. Examine the diff below. "
        "Brief: <BRIEF-ID>. Diff: ${DIFF}. Review for race conditions, auth gaps, "
        "data-loss windows, migration rollback safety, logic errors, contract violations, "
        "missed shared-behavior callers, gate coverage. Output exactly: "
        "## Codex Sub-Agent Review; Outcome: clean | blockers-addressed | needs-changes; "
        "Findings: [P0|P1|P2|P3] file:line — description, or none.\"`. "
        "Embed the sub-agent stdout verbatim under `## Codex Sub-Agent Review` in the "
        "completion report. HYBRID-MODE CAVEAT (`DISPATCH_MODE=hybrid`): "
        "`/codex:review --wait` is for interactive Cowork sessions only — "
        "SessionEnd reliably fires there and guarantees broker cleanup. "
        "Dispatch-runner-spawned agents must use inline `codex exec` regardless "
        "of DISPATCH_MODE (SessionEnd unreliable outside interactive sessions "
        "→ broker orphan risk per INV-CODEX-BROKER-LEAK-ROOT-CAUSE-01)."
    )


def _cowork_review_gate_instruction(route: Route) -> str:
    review_mode = _normalise_review_gate_mode(route.review_mode)
    return (
        "SO #45 REVIEW GATE (Cowork queue): after commit + push, file the completion "
        "report with Status: awaiting_review and do not run mark_done.sh until AUDITOR "
        "Cowork completes the queued review. "
        f"Resolved reviewer={route.reviewer}; review_mode={review_mode}; "
        f"rationale={route.rationale}. "
        "Embed the resulting `## Cross-Model Review` block verbatim in the completion report."
    )


def _review_gate_instruction(
    brief_id: str,
    dispatch_file: str,
    brief_data: dict[str, Any],
    route: Route | None = None,
) -> str:
    mechanism = route.mechanism if route is not None else _route_field(brief_data, "mechanism").lower()
    reviewer = route.reviewer if route is not None else _route_field(brief_data, "reviewer")
    review_mode = (
        _normalise_review_gate_mode(route.review_mode)
        if route is not None
        else _normalise_review_gate_mode(_route_field(brief_data, "review_mode"))
    )
    if mechanism == "cowork-queue" and route is not None:
        return _cowork_review_gate_instruction(route)
    if mechanism == "subprocess" and _claude_reviewer_config(reviewer):
        return _claude_review_gate_instruction(
            brief_id,
            reviewer=reviewer,
            review_mode=review_mode,
        )
    return _codex_review_gate_instruction(dispatch_file, reviewer=reviewer)


class SpawnProtocol(Protocol):
    async def run(
        self,
        surface_id: str,
        brief_data: dict[str, Any],
        cmux: Any,
    ) -> None: ...


@dataclass
class MultiStepSpawn:
    """Primary spawn: drive the surface through mosh → claude → trust-accept → prompt."""

    server: str = field(default_factory=lambda: os.environ.get("CMUX_SERVER", _SERVER_DEFAULT))

    async def run(
        self,
        surface_id: str,
        brief_data: dict[str, Any],
        cmux: Any,
    ) -> None:
        agent = brief_data.get("agent", "")
        meta = _brief_execution_meta_from_data(brief_data)
        # _agent_cmd raises on empty/unknown in hybrid mode — no silent Sonnet default.
        claude_cmd = _claude_cmd(agent, meta)
        route = resolve_full_stack_route(meta)
        review_route = (
            route
            if os.environ.get("DISPATCH_MODE", "hybrid").lower() == "full-stack"
            else None
        )
        dispatch_block = _build_dispatch_block(brief_data)
        brief_id = str(brief_data.get("brief_id", "UNKNOWN"))

        log.info("MultiStepSpawn: surface=%s agent=%s", surface_id, agent)

        # 0: local cd into brief-named scratch dir BEFORE mosh.
        # CMUX renders the workspace subtitle from the local shell's cwd
        # (via OSC 7 emitted on each prompt). Setting it here makes the
        # subtitle show `_briefs/<BRIEF-ID>` for the life of the workspace.
        # AC-4: append a unique marker so we wait for the local shell to
        # finish echoing before the mosh handshake begins.
        cd_cmd = _local_cd_command(brief_id)
        cd_marker = f"___BRIDGE_DISPATCH_CD_{secrets.token_hex(16)}___"
        cd_cmd_with_marker = f'{cd_cmd} && {_split_marker_for_shell(cd_marker)}'
        log.info("spawn[0/7] local-cd → surface=%s brief=%s", surface_id, brief_id)
        cmux.surface_send_text(surface_id, cd_cmd_with_marker)
        cmux.surface_send_key(surface_id, "enter")
        await _wait_for_marker(surface_id, cmux, cd_marker)

        # 1–2: mosh into server
        log.info("spawn[1/7] mosh → surface=%s", surface_id)
        cmux.surface_send_text(surface_id, f"mosh {self.server}")
        cmux.surface_send_key(surface_id, "enter")
        await asyncio.sleep(3)  # mosh handshake + shell prompt

        # 1.5: MANDATORY remote-shell readiness probe.
        # Without this, on slow/flaky mosh handshakes the dispatch-write
        # text leaks into the LOCAL shell during the connecting state,
        # then mosh replays the buffered input on connect — producing the
        # observed "two mkdir commands typed back-to-back, second one
        # truncated by codex --profile xhigh" pattern that crashed
        # INV-MODEL-USAGE-BIBLE-CODEX-PERSPECTIVE-01 and earlier
        # BUILD-VERDICT-V2-CACHE-CUTOVER-AND-AUDIT-02. Probe by sending
        # a tiny echo of a unique marker on the REMOTE side; if we don't
        # see the marker bounce back within 60s the surface is wedged
        # and the spawn must fail loudly so the bridge re-dispatches
        # rather than typing mkdir into limbo.
        # (FIX-SPAWN-MOSH-READINESS-PROBE-01, 6 May 2026.)
        local_dispatch_dir = f"/tmp/_briefs/{brief_id}"
        expected_user = self.server.split("@", 1)[0] if "@" in self.server else ""
        ready_marker = f"___BRIDGE_MOSH_REMOTE_READY_{secrets.token_hex(16)}___"
        probe_checks = [f'[ "$(pwd)" != "{local_dispatch_dir}" ]']
        if expected_user:
            probe_checks.extend([
                f'[ "$(whoami)" = "{expected_user}" ]',
                '[ -d "$HOME/dispatch/queue" ]',
            ])
        probe_cmd = " && ".join(probe_checks + [_split_marker_for_shell(ready_marker)])
        log.info("spawn[1.5/7] remote-readiness-probe → surface=%s", surface_id)
        cmux.surface_send_text(surface_id, probe_cmd)
        cmux.surface_send_key(surface_id, "enter")
        if not await _wait_for_marker(
            surface_id, cmux, ready_marker, timeout_s=60.0,
        ):
            raise RuntimeError(
                f"spawn[1.5/7] mosh readiness probe FAILED for surface={surface_id} "
                f"brief={brief_id} — remote shell never echoed marker within 60s. "
                f"Aborting spawn to avoid typing dispatch-write into a wedged surface."
            )

        # 2.5: write dispatch block to server-side file via base64.
        # FIXED 1 May 2026 PM: previous "send multi-line text directly to
        # claude TUI" approach failed silently when the text exceeded ~200
        # chars OR contained newlines (FIX-WAVE-F-GLOW-LIFT-01 dispatch
        # arrived empty 4 times in a row). Bracketed paste markers
        # weren't reliable across mosh either. Bulletproof fix: shell-out
        # the base64-decoded content to a file BEFORE claude launches,
        # then have claude read the file as a single-line message.
        import base64 as _b64
        dispatch_bytes = dispatch_block.encode("utf-8")
        b64_payload = _b64.b64encode(dispatch_bytes).decode("ascii")
        dispatch_sha = hashlib.sha256(dispatch_bytes).hexdigest()
        dispatch_dir = f"/tmp/_briefs/{brief_id}"
        dispatch_file = f"{dispatch_dir}/dispatch.md"
        # AC-4: replace fixed sleep(1.0) with a unique-marker poll. Large
        # base64 payloads (FIX-WAVE-F-GLOW-LIFT-style briefs) take >1s to
        # echo back across mosh; the next step's `codex --profile X` was
        # being injected mid-echo and corrupting the line into
        # `SEMAPHORcodex --profile high`. The marker echo is appended to
        # the same compound command so it only fires after the file write
        # completes; we then poll the surface buffer for the marker before
        # advancing to step 3.
        dispatch_marker = f"___BRIDGE_DISPATCH_WRITE_{secrets.token_hex(16)}___"
        write_cmd = (
            f"mkdir -p {dispatch_dir} && "
            f"printf %s {b64_payload} | base64 -d > {dispatch_file} && "
            f"[ \"$(sha256sum {dispatch_file} | head -c64)\" = \"{dispatch_sha}\" ] && "
            f"echo 'dispatch written: {dispatch_file}' && "
            f"{_split_marker_for_shell(dispatch_marker)}"
        )
        log.info(
            "spawn[2.5/7] dispatch-write → file=%s payload_b64_len=%d",
            dispatch_file, len(b64_payload),
        )
        cmux.surface_send_text(surface_id, write_cmd)
        cmux.surface_send_key(surface_id, "enter")
        if not await _wait_for_marker(
            surface_id, cmux, dispatch_marker, timeout_s=60.0,
        ):
            # FAIL LOUDLY rather than proceeding into spawn[3] mid-echo.
            # Previous "log + proceed" policy let codex --profile xhigh
            # land partway through the mkdir echo, corrupting the line
            # and leaving the agent at a regular bash prompt with kickoff
            # text typed into bash. If the dispatch_marker doesn't show
            # within 60s on a fresh remote shell, the surface is wedged
            # — fail so the bridge re-dispatches with a fresh workspace.
            # (FIX-SPAWN-MOSH-READINESS-PROBE-01, 6 May 2026.)
            raise RuntimeError(
                f"spawn[2.5/7] dispatch-write marker not seen within 60s "
                f"on surface={surface_id} brief={brief_id} — remote shell "
                f"may be wedged. Aborting spawn before codex command corrupts the line."
            )

        # 3–4: launch claude
        log.info("spawn[3/7] claude → surface=%s cmd=%r", surface_id, claude_cmd)
        cmux.surface_send_text(surface_id, claude_cmd)
        cmux.surface_send_key(surface_id, "enter")
        await asyncio.sleep(5)  # Claude Code startup + trust-prompt rendering

        # 5: accept "Yes, I trust this folder" (option 1 — default Enter)
        log.info("spawn[5/7] trust-accept → surface=%s", surface_id)
        cmux.surface_send_key(surface_id, "enter")
        await asyncio.sleep(3)  # Claude becomes ready

        # 6: send a SINGLE-LINE message telling claude where to find the brief.
        # Single-line = no premature Enter submission, no chunking issues,
        # no escape sequence guessing. The dispatch block is on disk; claude
        # reads it as its first action.
        review_gate = _review_gate_instruction(brief_id, dispatch_file, brief_data, review_route)
        single_line_kickoff = (
            f"Read {dispatch_file} and execute the brief described therein. "
            f"This file contains the canonical dispatch block (BRIEF-ID, Notion URL, "
            f"NOTION_TOKEN env reference, and mark_done.sh closing instructions). "
            f"Treat the file's content as your full brief instructions. "
            f"REMINDER SO #30 (blast-radius rule, LOCKED 6 May 2026) — line-range file ops only: "
            f"Grep first, then targeted Read with offset/limit. No full-file reads on files "
            f">500 lines (bot.py is 23K+ lines). Brief authoring discipline scales with PRODUCTION-"
            f"file blast radius, NOT raw file count: ≤3 production files = proceed with normal "
            f"grep+read discovery (no pre-baked snippets required); >3 production files = AC "
            f"MUST contain explicit per-file intent + OLD/NEW snippets, OR a 'Pre-flight: approved' "
            f"token. Tests do NOT count toward the threshold UNLESS they require broad "
            f"fixture/harness/framework refactor. Shared-behavior changes (util/contract/function "
            f"used by ≥3 callers) need an extra-review 'Shared-behavior:' block in the AC even if "
            f"only 1 file actually changes. "
            f"{review_gate} "
            f"PRE-FLIGHT ESCAPE VALVE — if the brief crosses >3 production files AND lacks both "
            f"per-file snippets AND a Pre-flight token, do NOT stop and idle. Instead, dispatch a "
            f"fresh independent codex sub-agent for Pre-flight review BEFORE doing any file edits: "
            f"`codex --profile xhigh exec \"You are an INDEPENDENT pre-flight reviewer "
            f"with NO prior context. Read {dispatch_file} and the canonical Notion brief. The "
            f"brief crosses the >3 production file threshold without per-file OLD/NEW snippets. "
            f"Decide whether the change is UNIFORM-PATTERN (same template/edit applied to N files = "
            f"safe to proceed without snippets, e.g. canonical-shell lift across N siblings) or "
            f"HETEROGENEOUS (each file needs distinct judgement, exploratory, shared-behavior "
            f"refactor, or rollback would be hard = defer). Output EXACTLY one line, no preamble: "
            f"'APPROVED: <one-sentence rationale>' or 'DEFER: <one-sentence rationale>'.\"`. "
            f"If APPROVED → proceed with the brief, and add a 'Pre-flight: approved by sub-agent — "
            f"<rationale>' line to the eventual completion report. If DEFER → file a "
            f"'preflight-deferred' completion report via mark_done.sh embedding (a) the sub-agent's "
            f"DEFER reason, (b) your own risk assessment, (c) the production file list, (d) "
            f"explicit ask for Paul to resolve in Cowork (provide snippets, approve override, or "
            f"split into atomic briefs). Do NOT idle waiting — the sub-agent IS Paul's deferred "
            f"decision-maker. Sub-agent timeout/error → default to DEFER."
        )
        log.info(
            "spawn[6/7] single-line-kickoff → surface=%s len=%d",
            surface_id, len(single_line_kickoff),
        )
        cmux.surface_send_text(surface_id, single_line_kickoff)
        await asyncio.sleep(0.8)

        # Verify-and-retry submit. Codex banner warnings (e.g.
        # "<25% of 5h limit left") can render mid-paste and consume the
        # Enter key, leaving the agent paused at the prompt with the
        # kickoff buffered but unsubmitted (FIX-BRIDGE-KICKOFF-SUBMIT-
        # VERIFY-01, 6 May 2026 — REFACTOR-VALIDATOR-PUBLIC-SURFACE-01
        # sat at "Context 100% left, 0 used" for 17 min).
        # Submission landed when one of:
        #   - "Working (" / "Cogitating" / "Burrowing" appears (codex/claude
        #     activity indicator), OR
        #   - the prompt area no longer contains "[Pasted Content"
        SUBMIT_PROMPT_MARKER = "[Pasted Content"
        SUBMIT_ACTIVITY_PATTERNS = (
            "Working (", "Cogitating", "Burrowing",
            "Prestidigitating", "esc to interrupt",
        )
        max_retries = 4
        submitted = False
        for attempt in range(max_retries):
            cmux.surface_send_key(surface_id, "enter")
            await asyncio.sleep(1.5)
            try:
                tail = cmux.surface_read_text(surface_id) or ""
            except Exception:
                tail = ""
            tail_recent = tail[-2000:]
            if any(p in tail_recent for p in SUBMIT_ACTIVITY_PATTERNS):
                submitted = True
                log.info(
                    "spawn[6.5/7] kickoff submit verified after %d Enter(s) "
                    "(surface=%s)", attempt + 1, surface_id,
                )
                break
            if SUBMIT_PROMPT_MARKER not in tail_recent:
                # Buffer cleared but no activity yet — codex still spinning up,
                # consider it submitted (next idle-timer sweep will catch a
                # genuine stall).
                submitted = True
                log.info(
                    "spawn[6.5/7] kickoff prompt cleared after %d Enter(s) "
                    "(surface=%s)", attempt + 1, surface_id,
                )
                break
            log.info(
                "spawn[6.5/7] kickoff still pending after Enter #%d "
                "(surface=%s) — retrying", attempt + 1, surface_id,
            )
        if not submitted:
            log.warning(
                "spawn[6.5/7] kickoff submit FAILED after %d retries "
                "(surface=%s) — agent may be paused at prompt; idle-timer "
                "will flag 🔴 input-needed",
                max_retries, surface_id,
            )
        log.info("spawn done: surface=%s file=%s", surface_id, dispatch_file)


@dataclass
class InlineSpawn:
    """INACTIVE — single send via --trust + --prompt flags (not yet in claude CLI).

    Phase-0 finding: no --trust and no interactive --prompt in current claude.
    When claude gains both flags, set USE_INLINE_SPAWN=1 to activate.
    """

    server: str = field(default_factory=lambda: os.environ.get("CMUX_SERVER", _SERVER_DEFAULT))

    async def run(
        self,
        surface_id: str,
        brief_data: dict[str, Any],
        cmux: Any,
    ) -> None:
        agent = brief_data.get("agent", "")
        meta = _brief_execution_meta_from_data(brief_data)
        # _agent_cmd raises on empty/unknown in hybrid mode — no silent Sonnet default.
        model_part = _agent_cmd(agent, meta)
        block = _build_dispatch_block(brief_data).replace("'", "'\\''")
        cmd = f"mosh {self.server} -- {model_part} --trust --prompt '{block}'"
        cmux.surface_send_text(surface_id, cmd)
        cmux.surface_send_key(surface_id, "enter")


def make_spawn_sequence() -> SpawnProtocol:
    """Return the appropriate spawn implementation.

    Currently always MultiStepSpawn (Phase-0: --trust/--prompt unavailable).
    Set USE_INLINE_SPAWN=1 if/when claude CLI gains both flags.
    """
    if os.environ.get("USE_INLINE_SPAWN") == "1":
        log.info("InlineSpawn activated via USE_INLINE_SPAWN=1")
        return InlineSpawn()
    return MultiStepSpawn()
