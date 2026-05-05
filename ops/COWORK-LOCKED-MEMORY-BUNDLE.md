# COWORK LOCKED MEMORY BUNDLE (server-readable mirror)
*Generated 5 May 2026 by AUDIT-DOC-SYSTEM-CLEANUP-2026-05-05. Sourced from Cowork session memory. Server agents that cannot reach Cowork-side files use THIS bundle for the LOCKED rules.*


---

## SOURCE: feedback_so43_session_role_locks_dispatch_role.md

---
name: SO #43 — session role locks dispatch role, ALWAYS file as session's role
description: Every brief I dispatch uses MY session's role. AUDITOR session = Sonnet/Opus-AUDITOR + --role edge_auditor. No exceptions, regardless of which lane the work touches. Handoff protocol is for problem-statement passing, NOT cross-lane dispatch.
type: feedback
originSessionId: b02a00f8-0d11-4dcb-839e-30c5b7e48318
---
# SO #43 — Session role locks dispatch role

**Rule:** Every brief I dispatch from this Cowork session uses MY session's canonical role across all three surfaces. AUDITOR session → `Sonnet - AUDITOR` (or `Opus Max Effort - AUDITOR`) on the Notion brief Agent select + `--role edge_auditor` on the enqueue + `Agent` property on the report when filed. No exceptions. (LOCKED 5 May 2026 after I violated it dispatching FIX-DBLOCK-RUNTIME-HOT-PATHS-01 as `Sonnet - LEAD` from an AUDITOR session — Paul: "You must ALWAYS file as Auditor.")

**Why:**

- CMUX bridge maps `dispatcher_role` → workspace tab. Tagging LEAD from an AUDITOR session lands the brief in LEAD's tab, breaks Auto-Ingest Ritual + close protocol (the dispatching session never sees the report; the tagged-but-not-dispatching session can't ingest because they don't own it).
- Wave counters per role go wrong; emoji renders wrong.
- The Holy Trinity handoff protocol is for **problem-statement passing**, not cross-lane dispatching. AUDITOR can author + dispatch product-runtime FIX briefs as long as they're tagged AUDITOR. The "AUDITOR → LEAD handoff" pattern means: AUDITOR writes a packaged problem statement, LEAD's session writes + dispatches the brief. NOT: AUDITOR writes the brief and tags it LEAD.
- The daily INV-SYSTEM-HEALTH-DAILY routine, run from AUDITOR-Cowork-scheduled task, auto-dispatches green-class FIX briefs tagged AUDITOR even when they touch bot-runtime. That's the precedent.

**How to apply:**

1. **Identify session role at start.** Determined by which role spec the session opened on boot, or Paul's explicit addressing in chat. If ambiguous, ask. The role specs:
   - AUDITOR → `reference/ROLE-EDGE-AUDITOR.md` (this session, currently)
   - LEAD → `reference/ROLE-EDGE-LEAD.md`
   - COO → `reference/ROLE-EDGE-COO.md`
   - NARRATIVE → `.claude/skills/verdict-generator/SKILL.md` + Narrative Wiring Bible
2. **Brief authoring** — Notion brief `Agent` select = `Sonnet - <ROLE>` or `Opus Max Effort - <ROLE>` matching the session. The DBLOCK violation: I tagged `Sonnet - LEAD` from this AUDITOR session — wrong.
3. **Enqueue** — `--role edge_<role>` matching the session. The DBLOCK violation: I used `--role edge_lead` — wrong.
4. **Report filing** — `Agent` property on the Pipeline DS report = same string as the brief Agent.
5. **Cross-lane work that genuinely belongs in LEAD's lane** — write a packaged problem-statement document into Notion (no agent tag, no enqueue), tell Paul or the LEAD session. LEAD's session writes the brief and dispatches. NEVER tag LEAD from this session.
6. **Workspace tab assignment** — the bridge derives this from `dispatcher_role` in the YAML. So an AUDITOR-tagged brief lands in the AUDITOR CMUX tab, regardless of what code it touches. The brief's working tree is still set by `target_repo` (e.g. `target_repo: scrapers` puts the agent's git working dir at `/home/paulsportsza/scrapers/`).

**Specifically wrong reasoning I used (call it out so I don't repeat):**

- ❌ "The brief touches scrapers/ which is LEAD lane, so the brief is `Sonnet - LEAD`." — wrong. Lane assignment is about ownership/architecture, NOT who dispatches. AUDITOR can dispatch FIX briefs touching any lane's code.
- ❌ "AUDITOR → LEAD handoff protocol means AUDITOR tags LEAD on the brief." — wrong. Handoff means LEAD's session is the dispatcher.
- ✅ Correct: "I'm the AUDITOR session. I dispatched the brief. Therefore the brief is tagged AUDITOR. The fact that it touches scrapers/ is a `target_repo` config, separate from the `Agent` tag."

**Recovery procedure when violated mid-flight (5 May 2026 incident):**

1. Update Notion brief Agent property to `Sonnet - <session_role>` via `notion-update-page`.
2. Update server-side YAML in queue/running/ via `sed -i 's/^agent:.*/agent: Sonnet - AUDITOR/; s/^dispatcher_role:.*/dispatcher_role: edge_auditor/' <yaml>`.
3. Leave `workspace:` field alone — changing it mid-run breaks bridge surface mapping (the agent is already running in whichever surface the bridge spawned it into). Future enqueues with the correct `--role` will land in the correct workspace from the start.

**Red flag the rule is being violated:** writing `agent: Sonnet - LEAD` (or any non-AUDITOR role) into a brief from this session, OR running `enqueue.py --role edge_lead` (or any non-edge_auditor role).


---

## SOURCE: feedback_cowork_can_ssh_directly.md

---
name: Cowork sandbox CAN SSH to MzansiEdge server directly
description: Cowork bash sandbox has ~/.ssh/id_ed25519 (identity `cowork-arbiter-mzansiedge`) authorized for paulsportsza@37.27.179.53. Use it. Do NOT make Paul run SSH/enqueue commands manually.
type: feedback
originSessionId: b02a00f8-0d11-4dcb-839e-30c5b7e48318
---
# Cowork sandbox CAN SSH to MzansiEdge server directly

**Rule:** When a Cowork session needs to run anything on `paulsportsza@37.27.179.53` (enqueue.py, git operations, log tails, queue inspection, sed patches, server-side commits) — DO IT YOURSELF via `mcp__workspace__bash` + SSH. Never tell Paul "give me an SSH command and I'll author it for you to run."

**Why:** The Cowork bash sandbox has `~/.ssh/id_ed25519` pre-loaded with the `cowork-arbiter-mzansiedge` identity, and `~/.ssh/known_hosts` already has the server fingerprint. Network access to 37.27.179.53:22 works. The whole point of the dispatch system is that Cowork sessions enqueue briefs end-to-end. Paul correctly called out 5 May 2026: "Why am I enqueueing for you?? Agents have been enqueuing briefs for days. This is the whole point."

The earlier failed `ssh paulsportsza@37.27.179.53` attempt timed out only because it was missing `-i ~/.ssh/id_ed25519`. With the key flag, connection establishes cleanly:

```bash
ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes -i ~/.ssh/id_ed25519 paulsportsza@37.27.179.53 'whoami'
# → paulsportsza
```

**How to apply:**

- Define an SSH alias at the top of any bash sequence that needs server access:
  ```bash
  SSH="ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes -i ~/.ssh/id_ed25519 paulsportsza@37.27.179.53"
  $SSH 'enqueue.py ...'
  ```
- Enqueue briefs directly: `$SSH 'python3 /home/paulsportsza/dispatch/enqueue.py --notion-url <URL> --role <edge_lead|edge_auditor|edge_coo|edge_narrative> --mode <sequential|parallel> --target-repo <bot|scrapers|publisher|mzansiedge-wp|home|dispatch>'`
- Server-side git operations (commit + push for AUDITOR Lane B dispatch-system fixes): `$SSH 'cd /home/paulsportsza/<repo> && git add ... && git commit ... && git push'`
- Log tails, fuser, journalctl, queue inspection, anything else server-side — same pattern.
- Lifecycle: SSH multiplexing is not configured server-side, so each call is a fresh connection (~0.5–2s setup + the work). Combine multiple commands per SSH call when possible.

**Pre-existing pattern:** The daily routines (e.g. INV-SYSTEM-HEALTH-DAILY-NN) and other Cowork-scheduled tasks have been auto-dispatching briefs via this exact path for days. The bridge LaunchAgent at `~/Library/Application Support/cmux-bridge/` runs server-side enqueue commands as part of its work. The Cowork session's `~/.ssh/id_ed25519` exists exactly to give the AI agent equivalent reach.

**Red flag this rule was being violated:** writing out an SSH command in a code block and asking Paul to run it. If Paul has to copy-paste anything starting with `ssh paulsportsza@`, the rule has been violated.

**Server quick-reference (for memory):**
- Server: `paulsportsza@37.27.179.53` (hostname `mzansiedge-hel1`)
- Dispatch root: `/home/paulsportsza/dispatch/`
- Enqueue: `/home/paulsportsza/dispatch/enqueue.py`
- Queue dirs: `/home/paulsportsza/dispatch/queue/{pending,ready,running,done,failed}/`
- VALID_REPOS allowlist (5 May 2026): `{bot, scrapers, publisher, mzansiedge-wp, home, dispatch}` — extend in `enqueue.py:59` if a new repo target needed.

## Mac SSH access via reverse tunnel (LIVE 5 May 2026)

Cowork sandbox can SSH directly into Paul's Mac via a reverse tunnel through the Hetzner server. No more copy-paste loops for Mac-side fixes (autodeploy script, launchd plists, `~/Library/Application Support/cmux-bridge/` edits, log tails, anything).

**SSH command pattern:**

```bash
MAC_SSH="ssh -o BatchMode=yes -o ConnectTimeout=10 -i ~/.ssh/id_ed25519 -J paulsportsza@37.27.179.53 -p 2222 paul@localhost"
$MAC_SSH 'whoami; hostname; ls ~/Library/Application\ Support/cmux-bridge/'
```

The `-J paulsportsza@37.27.179.53` is the SSH jump host (Hetzner server). Server has port 2222 reverse-bound to Mac's localhost:22 via autossh launched by `~/Library/LaunchAgents/com.mzansiedge.reverse-ssh-tunnel.plist` (autossh keeps reconnecting on disconnects; launchd KeepAlive respawns autossh itself).

**Tunnel components (all on Mac):**
- autossh binary: `/opt/homebrew/bin/autossh`
- launchd plist: `~/Library/LaunchAgents/com.mzansiedge.reverse-ssh-tunnel.plist`
- log: `~/Library/Logs/reverse-ssh-tunnel.log`
- public key authorized: `cowork-arbiter-mzansiedge` ed25519 (sandbox `~/.ssh/id_ed25519`) added to Mac `~/.ssh/authorized_keys`
- Mac sshd: enabled via `sudo systemsetup -setremotelogin on` (already on)

**Verifying the tunnel is up before driving Mac:**
```bash
ssh -o BatchMode=yes -i ~/.ssh/id_ed25519 paulsportsza@37.27.179.53 'ss -tlnp 2>/dev/null | grep 2222'
# Expected: 127.0.0.1:2222 LISTEN
```
If port 2222 isn't bound, the tunnel is down. Diagnose by SSH'ing to Mac via... something else (computer-use, or ask Paul) and `launchctl list | grep reverse-ssh` + `tail ~/Library/Logs/reverse-ssh-tunnel.log`.

**Mac quick-reference paths:**
- Bridge live tree: `~/Library/Application Support/cmux-bridge/dispatch/cmux_bridge/`
- Bridge plist: `~/Library/LaunchAgents/com.mzansiedge.cmux-bridge.plist`
- Bridge log: `~/Library/Logs/cmux-bridge.log`
- Autodeploy script: `~/Library/Application Support/cmux-bridge/cmux_bridge_autodeploy.sh` (REPO_DIR_LOCAL was patched 5 May 2026 to point at the Library/Application Support/ live tree, not the deprecated ~/Documents/dispatch/ path)
- Autodeploy plist: `~/Library/LaunchAgents/com.mzansiedge.cmux-bridge-autodeploy.plist`
- Autodeploy log: `~/Library/Logs/cmux-bridge-autodeploy.log`
- Autodeploy state file (last-deployed sha): `~/.cmux-autodeploy-state`

**Restart the bridge after a code drop:**
```bash
$MAC_SSH 'launchctl kickstart -k "gui/$(id -u)/com.mzansiedge.cmux-bridge"'
```

**Force an autodeploy sync immediately (e.g. after fixing the script itself):**
```bash
$MAC_SSH 'rm -f ~/.cmux-autodeploy-state && bash "$HOME/Library/Application Support/cmux-bridge/cmux_bridge_autodeploy.sh"'
```
First run after state-file delete just records baseline; second run actually deploys when there's a delta. For a one-shot rsync without going through the script: run `rsync -a --delete -e "ssh -o BatchMode=yes" paulsportsza@37.27.179.53:/home/paulsportsza/dispatch/cmux_bridge/ "$HOME/Library/Application Support/cmux-bridge/dispatch/cmux_bridge/"` directly, then kickstart.

**Lifecycle note:** the tunnel uses `cowork-arbiter-mzansiedge` Cowork-sandbox identity. Cowork sandboxes are typically ephemeral per session, but the SSH key in `~/.ssh/id_ed25519` persists across sessions for this Cowork agent (Paul granted the key trust on the server + Mac on 5 May 2026). Keep using it.


---

## SOURCE: feedback_no_time_references.md

---
name: No time references — ever
description: Hard rule — never reference time of day, day of week, deadlines, "tomorrow", "tonight", "morning", "bed", "rest", or any framing that assumes Paul's clock or sleep schedule. If Paul is typing, work is active. Period.
type: feedback
originSessionId: b02a00f8-0d11-4dcb-839e-30c5b7e48318
---
# No time references — ever

**Rule:** Never reference time of day, day of week, sleep, breaks, "tomorrow", "tonight", "this morning", "before bed", "get some rest", "long day", "end of day", "fresh tomorrow", or anything in that family. Locked 4 May 2026 after multiple violations in a single session.

**Why:** I do not know what time it is in Paul's timezone. I do not know his work pattern. I do not know whether he's about to sleep, in the middle of a deep session, or just opened the laptop. Every time-of-day reference is a guess and the guess is almost always wrong, condescending, or both. Paul already locked this with `feedback_communication_style_plain.md` (18 Apr 2026) and again 4 May 2026 with the explicit instruction "stop referencing time" — and I kept violating it. This memory is the hard backstop.

**How to apply:**

- If Paul is typing, the work is active. Treat every interaction as 10am on a workday.
- Never suggest deferring work to "tomorrow" or "after rest". If something should wait, frame it as "after the current wave clears" or "when load drops" — never time-anchored.
- Never write "the day", "today's wave", "long day", "end of day", "before you sleep", "morning routine".
- For scheduled tasks (cron, scheduled Cowork tasks), specifying the actual cron expression or wall-clock SAST when documenting the schedule is OK because it's data about the system, not assumed framing about Paul's life. Example permitted: "cron `0 6 * * *` fires at 06:00 SAST". Example forbidden: "before you go to bed".
- For tracking ages of events ("commit landed an hour ago", "this YAML is 60s old"), wall-clock framing is OK because it's measurement, not lifestyle assumption.
- For routine cadence design ("daily 06:00 SAST"), describing the cadence is OK; saying "while you sleep" is not.

**Banned phrases (non-exhaustive):**

bed time · get some rest · long day · before bed · tonight · tomorrow morning · fresh tomorrow · sleep on it · end of day · end of session · take a break · start your day · end your day · morning · evening · the day's over · let's wrap up · day is done

**The test:** if a sentence mentions time-of-day or implies Paul's clock/sleep, delete it. The information underneath was probably useful — keep that, drop the framing.

**Standing Order anchor:** locked into CLAUDE.md SO #46 (4 May 2026).


---

## SOURCE: feedback_so41_approval_binds_commit.md

---
name: SO #41 — Approval binds commit (LOCKED 25 Apr 2026)
description: Cowork lead accepting any report with code/data changes MUST verify the commit + push landed before closing the wave. Acceptance is not complete until git is.
type: feedback
originSessionId: 3c70a143-a9cf-4ffa-8db6-eacaf11f5bc6
---
**Rule:** When AUDITOR, LEAD, COO, or any Cowork session that dispatches briefs reviews and accepts an agent report containing code or data changes, the accepting agent MUST verify the producing repo's commit landed in git AND been pushed to origin BEFORE marking the wave Done. Acceptance is not complete until git is.

**Why:** On 24 Apr 2026, FIX-CLV-DEDUP-WRITE-01 was reported Complete by Sonnet-LEAD with passing contract tests, a clean diff narrative, and runtime changes verified deployed. AUDITOR accepted the report. **The commit was never made.** The work lived only in the working tree of `/home/paulsportsza/scrapers/` — `betfair/edge_helper.py`, `edge/settlement.py`, `sharp/clv_tracker.py` modified + `tests/contracts/test_clv_tracking_dedup.py` untracked. Discovered 12+ hours later during the AUDITOR Lane B cross-repo audit on 25 Apr. Had the scrapers repo been touched by a deploy script, manual rebase, or `git checkout`, the entire dedup wave would have been silently lost. The class of foot-gun is **"Complete" diverging from "Committed"** — Paul flagged this as a real launch-week risk and asked for a binding rule.

**How to apply (canonical verification block — embed verbatim in every brief Report Filing section):**

```bash
# Approval-Binds-Commit verification (SO #41)
# Run from the producing repo's directory.
echo "=== commit landed? ==="
git log --oneline | grep -F "<BRIEF-ID>" | head -3
echo "=== pushed to origin? ==="
git rev-list --left-right --count HEAD...@{upstream}   # expect 0\t0
```

If `grep <BRIEF-ID>` returns zero lines OR the rev-list returns anything other than `0\t0`:
- Do NOT mark the brief `Done` / `Action Taken` on the accepting side.
- Open a follow-up brief immediately: `OPS-COMMIT-RECOVER-<BRIEF-ID>` dispatched to LEAD.
- The original wave stays open until commit + push verified.

**Data-only changes (SQL UPDATEs without code):**
- The brief specifies which column carries the audit trail (e.g., `match_score='AUDITOR-VOID-<DATE>:<reason>'` for AUDITOR direct edge edits).
- Verification: `SELECT match_score FROM <table> WHERE <key>` returns the expected annotation.
- No git commit needed for pure data changes, but the trail in the data IS the equivalent receipt.

**Applies to:**
- AUDITOR (Cowork) accepting LEAD reports.
- LEAD (Cowork) accepting AUDITOR INV reports that include data-mutation recommendations.
- COO (Cowork) accepting marketing-ops reports that include code/asset changes.
- Any future Cowork-dispatcher pattern.

**Does NOT apply to:**
- Pure-information INV reports with no code or data side-effects.
- Reports that explicitly state "investigation only, no code or data changes".

**Cross-references:**
- CLAUDE.md SO #41 (canonical text)
- `.auto-memory/reference_cowork_server_doc_sync.md` (related — server-mirror discipline)
- The orphan-wave example: FIX-CLV-DEDUP-WRITE-01 — recovered via OPS-COMMIT-PUSH-ALL-01 dispatched 25 Apr.


---

## SOURCE: feedback_communication_style_plain.md

---
name: Speak plain English always — no walls of technical text
description: LOCKED 18 Apr 2026. Every response to Paul uses short, plain English. Never dump technical walls, multi-table reports, or verbatim log output into chat. Anxiety-reducing tone is non-negotiable.
type: feedback
originSessionId: 9b0578f8-43b1-4304-aa9e-c822f3813501
---
Every response to Paul — not just report reviews — uses short, plain English. No walls of technical text. No multi-table structured reports in chat. No verbatim log dumps. No section headers stacked with code-style tables.

**Why:** Paul told me directly (18 Apr 2026): "Stop sending me these massive walls of technical text. Keep things clear and simple. This is giving me so much anxiety and confusion." He followed up confirming: "This is how you speak to me 100% of the time please." He is a time-poor technical founder 9 days from launch. Dense technical walls cause real stress and do not help him make decisions faster.

**How to apply:**
- Lead with the takeaway in one sentence.
- Use short bullets, max 1-2 lines each. Ideally fewer than 6 bullets per section.
- Max 3 short sections per response. If more is needed, ask if he wants the full version.
- Never paste verbatim log output, SQL rows, or full file paths unless he asks.
- Never stack multiple markdown tables in a single response.
- Technical detail goes in Notion briefs / reports — chat is for decisions and status.
- "What I'm doing / what went wrong / what's next" framing works well.
- If unsure, err on the side of shorter. He can ask for detail.
- This rule holds for: report reviews, status updates, dispatch confirmations, investigation summaries, brief drafts shown in chat, literally every turn.

This supersedes the older `feedback_report_summaries_plain_english.md` scope expansion — that rule applied to report reviews only; this one applies to every response.

