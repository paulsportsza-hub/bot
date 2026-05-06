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
import hashlib
import logging
import os
import secrets
from dataclasses import dataclass, field
from typing import Any, Protocol


log = logging.getLogger(__name__)

_SERVER_DEFAULT = "paulsportsza@37.27.179.53"

# AC-4 — step 0 + 2.5 prompt-return marker wait.
# Replaces fixed asyncio.sleep() with a unique-marker echo + poll. Kills the
# race where a large base64 dispatch.md write was still echoing when the
# next command (`codex --profile high`) was injected, producing the
# `SEMAPHORcodex --profile high` corruption observed 2026-05-02.
_PROMPT_WAIT_POLL_S: float = 0.2
_PROMPT_WAIT_TIMEOUT_S: float = 60.0


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


def _agent_cmd(agent: str) -> str:
    """Build the executor CLI command for this brief's Agent select.

    Returns a shell-ready command string like 'codex --profile xhigh' or
    'claude --model sonnet'. Routing v1 dispatches to either codex or
    claude depending on the agent string."""
    parts = _model_flags(agent)
    return " ".join(parts)


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
        # _model_flags raises on empty/unknown — no silent Sonnet default.
        claude_cmd = _claude_cmd(agent)
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
            f"SO #45 REVIEW GATE (pure-codex mode, LOCKED 6 May 2026): after commit + push, "
            f"before mark_done.sh, run a fresh inline Codex sub-agent review with "
            f"`DIFF=$(git show --stat --patch HEAD); codex --profile xhigh exec "
            f"\"You are an INDEPENDENT reviewer with NO prior context. Examine the diff below. "
            f"Brief: <BRIEF-ID>. Diff: ${{DIFF}}. Review for race conditions, auth gaps, "
            f"data-loss windows, migration rollback safety, logic errors, contract violations, "
            f"missed shared-behavior callers, gate coverage. Output exactly: "
            f"## Codex Sub-Agent Review; Outcome: clean | blockers-addressed | needs-changes; "
            f"Findings: [P0|P1|P2|P3] file:line — description, or none.\"`. "
            f"Embed the sub-agent stdout verbatim under `## Codex Sub-Agent Review` in the "
            f"completion report. HYBRID-MODE CAVEAT (`DISPATCH_MODE=hybrid`, Claude "
            f"executor only): `/codex:review --wait` remains canonical there; in "
            f"pure-codex use only the inline `codex --profile xhigh exec` pattern above. "
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
        # _model_flags raises on empty/unknown — no silent Sonnet default.
        model_part = " ".join(_model_flags(agent))
        block = _build_dispatch_block(brief_data).replace("'", "'\\''")
        cmd = f"mosh {self.server} -- claude {model_part} --trust --prompt '{block}'"
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
