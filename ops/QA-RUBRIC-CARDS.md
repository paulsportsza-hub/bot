# QA-RUBRIC-CARDS — Pre-Launch Product QA Rubric

**Version:** 3.0 (INV-QA-RUBRIC-OVERHAUL-01)
**Last rewrite:** 2026-04-21
**Author:** Opus Max Effort — LEAD
**Target product:** `@mzansiedge_bot` (live Telegram bot, `/home/paulsportsza/bot/bot.py`)
**Status:** Launch gate. A wave is NOT shippable until a full run of this rubric PASSes.

---

## 0. What This Is — And Why It Was Rewritten

This rubric is the single source of truth for pre-launch QA of the MzansiEdge
Telegram product. A passing score here is one of the hard gates before any
release to real users.

It was rewritten on 2026-04-21 to close three documented failure modes from
**QA-BASELINE-02** (`/home/paulsportsza/reports/sonnet-QA-BASELINE-02-20260421.md`),
in which a QA agent produced a fabricated **9.06/10 PASS** score while:

1. **Scoring filter list views as Edge Detail cards.** A1–A4 (Digest, Gold
   Filter, Silver Filter, Bronze Filter) were all scored on D7a (Verdict
   Voice) and D7b (Verdict Accuracy) even though none of those artefacts
   contain a verdict. The verdict only appears on the `edge:detail:{match_key}`
   Edge Detail card — which the agent never reached.
2. **Scoring D3 (Visual Correctness) on PNG-only cards.** B1 (My Matches)
   and B2 (Match Detail) are rendered as photos with no caption the agent
   could read. D3 was scored at 9.0 / 8.5 purely from imagination.
3. **Insufficient coverage.** Six card types were evaluated; onboarding was
   skipped entirely, payment (Stitch Express) was skipped entirely, only one
   sport/tier profile was used, and three of the six cards were empty states
   or filter lists.

**Paul's standard:** *The QA harness must give genuine, brutal, crystal-clear
feedback on every corner of the product. Fluff scores are worse than no scores
— they create false confidence.* This rubric exists to make those three
failure modes structurally impossible on the next run.

Every rule below is non-negotiable. Where a rule says **MUST**, a QA run that
violates it is automatically rejected and filed as `QA-INVALID`, regardless of
the numeric score produced.

---

## 1. Anti-Fluff Enforcement Rules (Read First, Apply Always)

These override every scoring rule below. If any of them fire, the score is
rejected before arithmetic begins.

### 1.1 Never score a dimension you cannot verify
If you cannot reach the card, cannot see the image, cannot read the caption,
or the required data is not in the DB — the correct cell value is
**`UNVERIFIABLE`**, not a guess. A dimension marked UNVERIFIABLE is excluded
from the weighted round score and explicitly flagged as a coverage gap in the
report.

### 1.2 Quote everything
Every caption, verdict text, button label, and onboarding copy block that
contributes to a score MUST be quoted verbatim in the report. If it is not
quoted, the score is rejected.

Paraphrase is not permitted. If the artefact is a photo, the caption quote
may be "(no caption — photo only)" and then the visual methodology (§8)
applies.

### 1.3 Every numeric claim needs evidence
A dimension score cell is only valid when the evidence column shows both:
- **Rendered value** — what the user sees, quoted verbatim.
- **Expected value** — from the DB (`odds.db` / `mzansiedge.db`) or from a
  directly-inspected code path.

"9.5 — it looked right" is rejected.

### 1.4 Navigation failures are SEV-1
If you cannot navigate to a required card type, that is a top-priority
defect. It is not a "skip". It goes in the defect table as SEV-1 with the
callback data or command you attempted. The round is still reported, with
that card as UNTESTABLE — but the defect stands.

### 1.5 A low score with evidence is more valuable than a high score without
The reviewer (Paul) is looking for genuine signal. If you have to choose
between "a defensible 6.2 with clear evidence" and "an impressive 9.0 built
on paraphrase", always choose the 6.2.

### 1.6 Banned phrases — these must never appear unedited in a QA report
- "looks good"
- "appears correct"
- "seems to be"
- "probably"
- "I assume"
- "based on the context"
Replace with a quoted observation or an UNVERIFIABLE marker.

---

## 2. Navigation Depth Requirements (The Card Taxonomy)

The biggest failure in QA-BASELINE-02 was confusing artefacts at different
points in the UI. The product has **different card types** along the happy
path, and they are **NOT interchangeable** for scoring purposes.

### 2.1 Card taxonomy — learn this before scoring

| Card ID | User path | Artefact | Contains verdict? | Contains full odds? | Rendered as |
|---|---|---|---|---|---|
| **C0-ONB** | `/start` (fresh user) — each onboarding step | Onboarding step (image + text + buttons) | No | No | Text + InlineKeyboardMarkup |
| **C1-DIGEST** | `/today` or `/picks` or tap `💎 Top Edge Picks` | Top Edge Picks **list** | No (summary only) | No (best odds per tip line) | **Photo** (PNG caption) OR HTML text (list) |
| **C2-FILTER** | From C1, tap a tier filter (Diamond/Gold/Silver/Bronze) | Tier-filtered **sub-list** | No | No | HTML text, ≤4 items per page |
| **C3-EDGEDETAIL** | From C1 or C2, tap `ep:pick:N` → `edge:detail:{match_key}` | **The Edge Detail card** — verdict, signals, risk, setup | **YES** | **YES (access-level gated)** | HTML caption or text |
| **C4-MM** | Tap `⚽ My Matches` | My Matches list | No | No | HTML text (with 📺 broadcast line) |
| **C5-MATCHDETAIL** | From C4, tap `yg:game:{event_id}` | Match Detail breakdown (narrative) | YES (narrative verdict) | YES | HTML text, 4-section narrative |
| **C6-SUBSCRIBE** | `/subscribe` | Plan picker | No | No | HTML text + InlineKeyboardMarkup |
| **C7-EMAIL** | From C6, tap a plan | Email prompt | No | No | HTML text |
| **C8-PAYLINK** | After email, Stitch Express fires | Payment link message (checkout URL button) | No | No | HTML text + URL button |
| **C9-PAYCONFIRM** | After Stitch webhook returns `COMPLETED` / mock `complete` | Payment confirmation push | No | No | HTML text |
| **C10-PAYFAIL** | After Stitch webhook returns `CANCELLED` / `EXPIRED` | Payment failure push | No | No | HTML text |
| **C11-SETTINGS** | Tap `⚙️ Settings` | Settings menu | No | No | HTML text + buttons |
| **C12-HELP** | Tap `❓ Help` or `/help` | Help screen | No | No | HTML text + buttons |
| **C13-GUIDE** | Tap `📖 Guide` | Guide topic menu + 6 topic pages | No | No | HTML text + buttons |
| **C14-RESULTS** | `/results` or `/track` | Edge Tracker (7D / 30D settled results) | No | No | HTML text |

> **D7 (Verdict) is ONLY applicable to C3 and C5.** Scoring D7 on any other
> card type is an automatic QA-INVALID.
> **Odds accuracy (D1) is applicable only to C1, C2, C3, C4, C5.**
> Filter views (C2) show best-odds-per-tip, not full market grids.

### 2.2 Minimum navigation path for a complete QA run

The QA run MUST exercise the following sequence, in order, at least once:

```
/start                                → C0-ONB flow 1 (fresh)
  (complete every step, full profile) → C0-ONB x5-7 steps
/today                                → C1-DIGEST
  tap Diamond filter                  → C2-FILTER (diamond)
  tap first Diamond pick              → C3-EDGEDETAIL (diamond)
  ↩ back
  tap Gold filter                     → C2-FILTER (gold)
  tap first Gold pick                 → C3-EDGEDETAIL (gold)
  ↩ back
  tap Silver filter                   → C2-FILTER (silver)
  tap first Silver pick               → C3-EDGEDETAIL (silver)
  ↩ back
  tap Bronze filter                   → C2-FILTER (bronze)
    (if bronze exists) tap a pick     → C3-EDGEDETAIL (bronze) — bronze/locked
tap ⚽ My Matches                     → C4-MM
  tap a match                         → C5-MATCHDETAIL
/subscribe                            → C6-SUBSCRIBE
  tap a paid plan                     → C7-EMAIL
  send valid email                    → C8-PAYLINK
  tap checkout URL                    → (external: stop here OR mock webhook)
  (mock-complete OR wait for webhook) → C9-PAYCONFIRM or C10-PAYFAIL
/results                              → C14-RESULTS
⚙ Settings                            → C11-SETTINGS
❓ Help                                → C12-HELP
📖 Guide                              → C13-GUIDE
/qa reset                             → end of run
```

Then repeat for a **second profile** with a different sport selection and a
forced tier via `/qa` (see §9).

### 2.3 How to tell C2 (filter) apart from C3 (detail)

| Signal | C2-FILTER (list) | C3-EDGEDETAIL (the real verdict card) |
|---|---|---|
| Header | "💎 Diamond Edges — Page 1/N" or similar | `🎯 {Home} vs {Away}` + 📅 kickoff + 🏆 league + 📺 broadcast |
| Contains `📋 <b>The Setup</b>` | No | **Yes** |
| Contains `🎯 <b>The Edge</b>` section | No | **Yes** |
| Contains `⚠️ <b>The Risk</b>` section | No | **Yes** |
| Contains `🏆 <b>Verdict</b>` section | No | **Yes** |
| Buttons row | one `ep:pick:N` per tip | `edge:detail` CTA + `hot:back:{page}` |

If the artefact you are scoring does not contain all four `📋 🎯 ⚠️ 🏆`
section headers in that order, it is **NOT C3-EDGEDETAIL** and D7a/D7b
scoring on it is automatically QA-INVALID.

---

## 3. Minimum Test Volume (Codified)

A QA run is only eligible for a PASS verdict if it meets **all** of the
following. Missing any one turns the overall verdict into CONDITIONAL at
best, FAIL more commonly.

- **≥ 10 cards evaluated per run.** Not the same card 10 times. 10 distinct
  card instances spanning ≥ 7 card types from §2.1.
- **≥ 2 complete onboarding flows** (both reach the summary + sticky
  keyboard), using different profiles:
  - Profile A: soccer-only + Bronze (free) + Conservative risk.
  - Profile B: multi-sport (≥ 3 sports) + forced-Gold (`/qa set_gold`) +
    Aggressive risk. Custom bankroll (R750 or R3000, not a preset).
- **≥ 3 sports covered** across the C3-EDGEDETAIL cards evaluated (e.g.
  soccer + rugby + cricket — combat acceptable if a live edge exists).
- **≥ 1 Diamond, ≥ 1 Gold, ≥ 1 Silver C3-EDGEDETAIL** card scored on its
  own verdict — not on a filter list. If the live bot does not have edges
  of a required tier at QA time, the tier must be marked **UNTESTABLE** in
  the report along with a timestamped query against `odds.db` proving there
  were no edges of that tier. Silent skip is rejected.
- **≥ 1 payment flow** executed end-to-end: `/subscribe` → plan → email →
  payment link. If `STITCH_MOCK_MODE=true`, test through to the mock
  confirmation. If mock mode is off, the flow stops at the payment link and
  the webhook step is flagged as `LIVE-NOT-EXECUTED`.
- **≥ 1 empty state per panel** attempted:
  - Bronze filter with no bronze edges today (if produced naturally).
  - My Matches when the user has no upcoming fixtures (use a fresh
    profile's state before teams are saved, or query
    `get_subscribers_for_event` for a known-empty window).
- **≥ 1 locked-tier state** seen: Bronze user viewing a Diamond edge (LOCKED
  access level per `tier_gate.get_edge_access_level`).

---

## 4. Dimensions D1 – D7 (Definitions Retained, Methodology Hardened)

The dimension set is unchanged from the prior rubric — Paul's note on the
brief confirmed the D1–D7 definitions are "mostly sound". Each dimension
below now includes an **observation procedure** specifying exactly what the
QA agent must capture to produce a defensible score.

All scores are on a **0.0 – 10.0 scale**, one decimal place, floor 0.0.

### D1 — Data Correctness (weight 30%)
*Do the numbers on the card match the DB?*

**Procedure:**
1. For each data field shown (odds, EV%, fair probability, confidence,
   kickoff, league, bookmaker, tier badge), quote the rendered value.
2. Query `odds.db` / `mzansiedge.db` for the same field. Required tables:
   - Odds: `odds_snapshots` filtered by `market_type='1x2'`
     (LOCKED — BUILD-MY-MATCHES-01: never omit this filter).
   - Edges: `edge_results`.
   - Narrative cache: `narrative_cache`.
   - Broadcast: `broadcast_schedule`.
   - User tier: `users.user_tier` via `get_effective_tier(user_id)`.
3. Score deducts 1.5 per mismatch on a numeric field, 1.0 per mismatch on a
   text field, capped at 0.0. A missing field the user expected to see is a
   0.5 deduction.

**Banned:** scoring D1 from "it looked right". Every value gets a source row.

### D2 — Content Completeness (weight 15%)
*Does the card include every element the design spec requires?*

**Procedure per card type:**

- **C1-DIGEST:** 7D hit-rate header, scan-breadth subline, "N Live Edges
  Found", N tip cards (≤ `HOT_TIPS_PAGE_SIZE=4`), footer CTA block,
  pagination buttons where applicable.
- **C3-EDGEDETAIL:** header block (🎯 match, 📅 kickoff, 🏆 league,
  📺 broadcast), `📋 The Setup`, `🎯 The Edge`, `⚠️ The Risk`,
  `🏆 Verdict`, SA Bookmaker Odds section (if access level permits), CTA
  button, back button, odds-comparison button where applicable.
- **C5-MATCHDETAIL:** same four narrative sections + odds table + CTA.
- **C4-MM:** per-match line (flags + `[N] {teams}` + tier badge), 📺
  broadcast line, sport filter row, pagination.
- **C6/C7/C8/C9/C10:** the exact elements required by `_subscribe_plan_text`,
  `_payment_ready_markup`, and the webhook-handler push texts.

Deduct 1.0 per required element missing. Zero out if the card is the wrong
card type (e.g. a filter list presented where a detail card was expected).

### D3 — Visual Correctness (weight 15%)
*Does the rendered pixel output match the design?*

**This is the dimension that was fabricated in QA-BASELINE-02.** See §8 for
the methodology decision and what an agent that cannot see images must do.

### D4 — Interaction Correctness (weight 5%)
*Do buttons route to the right handlers? Are `↩️` back paths intact?*

**Procedure:** For every inline button on the card, record the
`callback_data`, tap it (or simulate the tap), and observe the next card.
Expected routing lives in the `on_button()` router and is documented in the
CLAUDE.md "Callback Data Pattern" section. Any dead-end (no back button) or
any mis-route (tap lands on wrong card type) is a 2.0 deduction.

Locked rule: the back arrow must be `↩️`, never `🔙` (CLAUDE.md convention).

### D5 — Conformance to Content Laws (weight 5% — reallocated; see §5)
*Does the card honour the 6 Notification Content Laws (CLAUDE.md)?*

Procedure: scan the card body and defect out any of:
- Win guarantees ("guaranteed winner", "sure bet", "lock", "100%").
- Aggressive CTAs after 3+ consecutive misses (check
  `User.consecutive_misses` for the profile in use).
- More than one emoji per message section (counts per `📋/🎯/⚠️/🏆` block).
- Missing RG footer on trial / monthly / re-engagement messages.
- Any minimisation of a miss in a settled-result message.

Each hit is a 2.0 deduction.

### D6 — Performance / Responsiveness (weight 15%)
*Did the card arrive within the product SLA?*

**Procedure:** record wall-clock time from tap to first visible pixel of the
response message, using the Telethon client's message timestamps.

| Card | Warm SLA | Cold SLA | Fail threshold |
|---|---|---|---|
| C1-DIGEST | ≤ 2.0s | ≤ 8.0s | > 12s |
| C3-EDGEDETAIL (cache hit) | ≤ 1.0s | — | > 3s |
| C3-EDGEDETAIL (baseline, no LLM) | ≤ 2.0s | ≤ 5.0s | > 8s |
| C3-EDGEDETAIL (full generate) | — | ≤ 30s | > 45s |
| C4-MM | ≤ 1.0s | ≤ 5.0s | > 8s |
| C5-MATCHDETAIL | ≤ 2.0s | ≤ 30s | > 45s |
| C8-PAYLINK (Stitch Express) | — | ≤ 8.0s | > 15s |

Deduct 2.0 on first SLA miss, 5.0 on fail-threshold crossing. Zero out if
the card never arrives (that's a SEV-1 defect).

### D7a — Verdict Voice (weight 10% — C3 and C5 only)
*Does the verdict sound like a SA sports pundit at a braai, not a template?*

See §6 for worked examples of fail / pass / perfect.

### D7b — Verdict Accuracy (weight 10% — C3 and C5 only)
*Is every number in the verdict cross-checked against the card display?*

See §6 for the enforcement rule.

**Non-applicable cards contribute 0% to D7a/D7b.** The weight is
redistributed proportionally across D1–D6 for that card (e.g. D1 at 30% /
0.70 = 42.9% on a non-verdict card). The report MUST show the redistributed
weights explicitly in the card's score block.

---

## 5. Dimension Applicability Matrix

This is the table that tells a QA agent, for each card, exactly which
dimensions apply and which do not. An "✗" cell means "do not score this,
do not include it in arithmetic".

| Card | D1 Data | D2 Content | D3 Visual | D4 Interaction | D5 Laws | D6 Perf | D7a Voice | D7b Accuracy |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| C0-ONB | ✓ | ✓ | ✓ (see §8) | ✓ | ✓ | ✓ | ✗ | ✗ |
| C1-DIGEST | ✓ | ✓ | ✓ (see §8) | ✓ | ✓ | ✓ | ✗ | ✗ |
| C2-FILTER | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ |
| C3-EDGEDETAIL | ✓ | ✓ | ✓ (see §8) | ✓ | ✓ | ✓ | ✓ | ✓ |
| C4-MM | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ |
| C5-MATCHDETAIL | ✓ | ✓ | ✓ (see §8) | ✓ | ✓ | ✓ | ✓ | ✓ |
| C6-SUBSCRIBE | ✗ (no odds) | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ |
| C7-EMAIL | ✗ | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ |
| C8-PAYLINK | ✓ (amount, plan) | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ |
| C9-PAYCONFIRM | ✓ (plan, tier) | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ |
| C10-PAYFAIL | ✗ | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ |
| C11-SETTINGS | ✗ | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ |
| C12-HELP | ✗ | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ |
| C13-GUIDE | ✗ | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ |
| C14-RESULTS | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ |

**Weight redistribution formula:** when D7a + D7b do not apply, the 20%
they would carry is redistributed across D1–D6 pro rata to their nominal
weights. The card's score block MUST show both the nominal and the
redistributed weights.

---

## 6. Narrative Scoring — Worked Examples (D7a + D7b)

### 6.1 Mandatory quote rule
For every C3 and C5 card scored, the `🏆 Verdict` section — from the `🏆`
emoji to the next section break or the CTA block — **MUST be quoted
verbatim in the report**. If the verdict is inside a photo caption, the
caption quote counts. If it is not quoted, D7a and D7b are both rejected.

### 6.2 Worked example — FAILING verdict (score 3.0 – 4.9)
> 🏆 Verdict
> Based on the data, I would recommend backing the home side. The numbers
> favour them and this is a solid pick. Back Team A to win at 2.10 with
> Bet365.

**Why it fails:**
- Generic template language ("Based on the data, I would recommend…").
- No SA voice, no team nickname, no braai register.
- Wrong bookmaker (Bet365 is not in the SA bookmaker set).
- `2.10` odds unverified against card display — no cross-check.
- Opens with "I would" — banned register per TONE_BANDS (see
  `narrative_spec.py`).

Scoring: D7a 3.0 (no voice, template), D7b 4.0 (correct structure of a
pick, wrong bookmaker, no cross-check).

### 6.3 Worked example — PASSING verdict (score 7.5 – 8.9)
> 🏆 Verdict
> Bucs at home is a familiar story — the crowd lifts them, and Sundowns
> have been sweating away from Loftus. Back Orlando Pirates at 2.15 on
> Hollywoodbets. Size it normally, don't overcommit.

**Why it passes:**
- SA voice — "Bucs", "Loftus", "familiar story".
- Named SA bookmaker (Hollywoodbets).
- Clean call line with odds.
- Sizing guidance present, tone matches a Gold / confident band.
- No guarantee language, no banned phrase.

Scoring: D7a 8.5, D7b 8.0 assuming `2.15` and `Hollywoodbets` match the
card's odds display exactly.

### 6.4 Worked example — PERFECT verdict (score 9.5 – 10.0)
> 🏆 Verdict
> Amakhosi at FNB with Du Preez back in the mix — that's the angle the
> market hasn't priced in yet. Back Kaizer Chiefs to win at 2.34 on
> Betway. Indicators are doing their job here — the depth of support
> most edges don't get.

**Why it is perfect:**
- SA voice + SA venue reference.
- Name from the VERIFIED_DATA block (Du Preez — only usable if it's in
  the injected coach/player list for this match).
- `2.34` and `Betway` both cross-checked against the card's
  `💰 Best odds` line, exact match to two decimal places.
- Strong-band phrase ("indicators are doing their job") which is an
  `allowed` phrase in `TONE_BANDS["strong"]["allowed"]`.
- Zero banned phrases (no "guaranteed", no "lock", no "sure bet", no
  "tread carefully").

Scoring: D7a 10.0, D7b 10.0.

### 6.5 The number cross-check procedure (enforcement for D7b)
For every numeric token in the verdict (odds, percentages, amounts), the
report MUST show a two-column table for this card:

| Number in verdict | Same number on card display | Match? |
|---|---|---|
| 2.34 | `💰 2.34 (Betway)` | ✓ |
| Betway | `Betway` tag in odds section | ✓ |
| Kaizer Chiefs | `🎯 Kaizer Chiefs vs Mamelodi Sundowns` | ✓ |

Every mismatch is a 2.0 deduction on D7b. Two mismatches = D7b capped at
5.0. Three or more = D7b capped at 3.0 and the card flagged SEV-2.

### 6.6 Banned phrases in any verdict (enforce with `BANNED_NARRATIVE_PHRASES`)
Non-exhaustive — if in doubt, check `narrative_spec.TONE_BANDS` for the tone
band that applies:
- "guaranteed", "guaranteed winner", "sure bet", "lock", "nailed on".
- "Standard match variance applies."
- "Zero confirming indicators".
- "pure price edge with no supporting data".
- "tread carefully" (banned in `cautious` band since W84-Q3).
- "the numbers speak louder", "pure pricing call".
- "numbers-only play", "thin on supporting signals".
- "worth the exposure, not worth overloading" (banned in W84-Q16).

Any single hit = D7a capped at 4.0 and the card flagged SEV-2. Two or more
= D7a capped at 2.0 and the card flagged SEV-1.

### 6.7 Narrative pipeline compliance check (NARRATIVE-ACCURACY-01 — LOCKED 22 Apr 2026)

For every C3 and C5 card, the QA agent MUST verify the narrative was produced
by the accuracy-hardened pipeline before scoring D7a / D7b. These checks are
**prerequisites** — if they fail, D7a and D7b are both capped at 5.0 and the
card is flagged `QA-PIPELINE-MISS`.

**Check 1 — Validator evidence present**

Query `narrative_cache` for this `match_id`. Confirm the row contains non-null
`setup_validated` and `verdict_validated` fields set to `true`. If either is
`false` or `null`, the narrative was produced by the pre-v2 pipeline (no
validator ran). Log as `PIPELINE-MISS` and deduct 2.0 on D7b.

```sql
SELECT setup_validated, verdict_validated, setup_attempts, verdict_attempts
FROM narrative_cache WHERE match_id = ?;
```

**Check 2 — Sport-aware handler used**

Confirm the narrative does not contain football terminology for rugby or cricket
cards (e.g. "goals", "GPG", "home_record" for rugby; "shots", "clean sheet" for
cricket). One hit = SEV-2 flag; two or more = D7a capped at 3.0.

**Check 3 — CURRENT_STADIUMS compliance (EPL/PSL only)**

For football cards, confirm no legacy stadium name appears. Currently watched:
"Goodison" or "Goodison Park" for Everton = instant SEV-1 (Everton moved to
Hill Dickinson Stadium in August 2025). Add entries here as clubs move grounds.

**Check 4 — Validator false-positive awareness**

If `verdict_validated = false` but the narrative reads as factually accurate,
apply human override. The validator has a ~25% false-positive rate on arithmetic
derivations ("twelve wins from sixteen games" for W12+D2+L2=16) and standard
paraphrases ("winless in five"). A reviewer may override `verdict_validated`
if the claim is traceable to DERIVED CLAIMS via arithmetic. Document the
override with the specific claim and its arithmetic source.


---

## 7. Onboarding QA (C0-ONB)

Dedicated section because QA-BASELINE-02 skipped onboarding entirely.

### 7.1 Two profiles required (per §3)

**Profile A — new soccer-only Bronze user**
- `/start` as a user that has never interacted with the bot
  (`db.User.onboarding_done = False`).
- Experience: "Casual".
- Sports: tick only ⚽ Soccer.
- Teams: type "arsenal, chiefs" (tests the fuzzy matcher, tests EPL + PSL
  alias). Continue.
- Risk: Conservative.
- Bankroll: tap R200 (a preset).
- Notify: 07:00.
- Summary: confirm with "Let's go".
- Expected end state: sticky keyboard appears
  (`⚽ My Matches | 💎 Top Edge Picks | 📖 Guide / 👤 Profile | ⚙️ Settings | ❓ Help`).

**Profile B — multi-sport experienced user, forced Gold**
- `/start` (can reuse Profile A's chat after `/settings → Reset Profile`).
- Experience: "Experienced" (must auto-skip the Edge Explainer screen per
  Phase 0B — verify it skips).
- Sports: ⚽ Soccer + 🏉 Rugby + 🏏 Cricket.
- Teams: one per sport — "man city", "bulls", "proteas".
- Risk: Aggressive.
- Bankroll: tap "Custom", type "3000".
- Notify: 18:00.
- Summary → confirm.
- Then `/qa set_gold` to force Gold access for the rest of the run.

### 7.2 Per-step pass/fail checks

| Check | Pass criterion |
|---|---|
| First welcome message | Text says "Welcome to MzansiEdge, {name}!" with HTML escaped name |
| Reply keyboard removed during onboarding | `ReplyKeyboardRemove()` fires on first step |
| Step numbering | "Step 1/6 … Step 5/6" visible on respective steps |
| Sport toggles | Tapping `ob_sport:soccer` toggles `selected_sports` set |
| Fuzzy match celebration | "arsenal" → "✅ Arsenal — *Gooners forever!*" with team-specific cheer |
| Risk keyboard has Start Again button | `ob_nav:restart` present from Phase 0B |
| Bankroll presets | R50 / R200 / R500 / R1000 (per Phase 0D-FIX) |
| Custom bankroll accepts "3000" | Non-numeric rejected with retry prompt |
| Edge Explainer shown to Casual users | `_show_edge_explainer` fires before risk step |
| Edge Explainer **skipped for Experienced** | Goes straight from favourites to risk |
| Summary screen | Clean profile display with Edit buttons, bold `🎯 Experience:` label |
| Completion → welcome + CTAs | No Haiku-generated paragraph (removed in Phase 0D-FIX) |
| Community CTA button | Required per brief — check for community link button on completion message |
| Sport prefs persisted | `UserSportPref` rows exist for user_id with inferred league keys |
| Archetype classified | `User.archetype` is set (complete_newbie / eager_bettor / casual_fan) |
| Returning user skips onboarding | Second `/start` shows welcome-back, NOT the experience step |

Each failed check is a defect: SEV-1 if the step is blocking, SEV-2 if the
user can still proceed but sees something broken, SEV-3 for cosmetic.

### 7.3 Onboarding image vs text policy
Per the brief: "Does each step send an image or plain text? (target: all
images, per the product vision)". Until the all-image variant ships, the
QA agent simply **records** image/text per step. No score deduction, but the
log MUST contain the breakdown so Paul can see progress toward the target.

---

## 8. Visual Methodology (D3) — Decision: Option A (Vision Model)

Per the brief, the rubric must pick one of:
- **Option A — Vision model:** download each PNG and pass it to a
  vision-capable Claude call for a structured description, then score the
  description against the design spec.
- **Option B — UNVERIFIED marker + human review.**

### 8.1 Recommendation and reason

**Adopt Option A as the default.** Reasons:
1. The QA harness must be autonomous (Paul's standing note on the brief).
   Option B forces a human round-trip on every run and defeats the purpose
   of a pre-launch gate.
2. Claude Sonnet 4.6 with image input is available via the Anthropic API
   already wired into the bot (`ANTHROPIC_API_KEY` in `.env`). No new
   dependency or credential.
3. The Telethon harness (`tests/w91_p3_telethon_verdict_qa.py` and peers)
   already downloads Telegram photo media to disk — hooking a vision call
   in is a small change to the harness, not a rubric issue.

### 8.2 Procedure for Option A

For each card type with a photo artefact (C0-ONB image steps, C1-DIGEST
photo variant, C3-EDGEDETAIL photo variant where applicable, C5-MATCHDETAIL
photo variant where applicable):

1. Download the photo via Telethon (`MessageMediaPhoto` → `download_media`)
   to `/home/paulsportsza/reports/e2e-screenshots/{run_id}/{card_id}.png`.
2. Call Claude Opus 4.7 (`claude-opus-4-7`) with the image and the
   following structured prompt:
   ```
   You are a QA inspector for a SA sports betting app called MzansiEdge.
   Describe this card image in structured JSON with exactly these fields:
   {
     "tier_badge_emoji": "<one of 💎 🥇 🥈 🥉 or null>",
     "tier_badge_colour": "<dominant colour of the tier badge>",
     "home_team_name_visible": "<text>",
     "away_team_name_visible": "<text>",
     "odds_value_visible": "<text or null>",
     "bookmaker_name_visible": "<text or null>",
     "confidence_bar_present": <true|false>,
     "confidence_bar_fill_pct": <number or null>,
     "signal_dots_visible": <number of dots shown>,
     "sa_flag_present": <true|false>,
     "safe_gambling_footer_visible": <true|false>,
     "sections_visible_in_order": ["Setup","Edge","Risk","Verdict"] or subset,
     "layout_issues": "<free text, describe any clipping, overlap, or off-brand rendering>"
   }
   Output ONLY the JSON. Do not add prose.
   ```
3. Score D3 against the expected values:
   - Tier badge emoji matches the card's tier (from `edge_results.tier` or
     `_display_tier`): full credit or 3.0 deduction.
   - Home/away names match the `match_key`: full credit or 2.0 deduction per
     mismatch.
   - Odds and bookmaker match the text caption (cross-reference with D1).
   - Sections (for detail cards): all four present in the correct order —
     1.0 deduction per missing section.
   - `layout_issues` is blank OR contains only minor notes: full credit.
     Any structural issue (clipping, overlap, broken emoji): 2.0 deduction.

4. The vision model's JSON output MUST be included verbatim in the report
   for every scored D3. No paraphrase.

### 8.3 Fallback to Option B
If Option A cannot execute (API down, vision model error, quota
exhaustion), the agent MUST:
- Mark D3 as `UNVERIFIED — vision model unavailable` for every affected
  card.
- Recalculate the round score with D3 excluded and the remaining weights
  redistributed pro rata.
- Append a **Human Visual QA Checklist** to the report listing every card
  that needs human review, with the path to the downloaded PNG.

Silent D3 scoring without pixel access is QA-INVALID and will cause
auto-rejection of the entire run.

---

## 9. Tier Simulation via `/qa` Commands

The bot ships with an admin-gated tier override system
(`bot.py:27127`, `_QA_TIER_OVERRIDES`). Use this instead of touching
`user_tier` in the DB.

| Command | Effect |
|---|---|
| `/qa set_bronze` | Force bronze for the caller's user_id (in-memory) |
| `/qa set_gold` | Force gold |
| `/qa set_diamond` | Force diamond |
| `/qa reset` | Clear the override (returns to real DB tier). Does NOT touch DB subscription state |
| `/qa tips_bronze` | Send a Hot Tips render as if caller were bronze |
| `/qa tips_gold` | Send a Hot Tips render as if caller were gold |
| `/qa tips_diamond` | Send a Hot Tips render as if caller were diamond |

**Mandatory:** the QA run MUST exercise `/qa set_bronze` and
`/qa set_gold` at minimum (Diamond is the natural default for Profile B).
The report MUST log every `/qa` command sent and the effective tier before
and after.

**Locked rule:** QA must never `db.set_user_tier()`. That destroys real
subscription state (see W84-ACC1). Only `_QA_TIER_OVERRIDES` (via `/qa`) is
permitted.

---

## 10. Payment Flow QA (Stitch Express — `services/stitch_service.py`)

QA-BASELINE-02 skipped this entirely. It is non-optional.

### 10.1 Required surfaces per payment attempt

| Step | Artefact | What to verify |
|---|---|---|
| Initiation | `/subscribe` → C6-SUBSCRIBE | Plan picker shows correct prices from `config.STITCH_PRODUCTS`; founding button only when `founding_left > 0` |
| Plan select | tap `sub:tier:gold_monthly` → C7-EMAIL | "Selected: {tier_name} ({price})" message, email prompt, awaiting_email state set |
| Email submit | send `qa+{timestamp}@mzansiedge.co.za` | Accepts valid email, creates `Payment` row with `billing_status='awaiting_webhook'` |
| Payment link | Stitch Express call fires | `C8-PAYLINK` arrives ≤ 8s warm, ≤ 15s cold |
| Link opens Express | hover / inspect URL | Must contain `express.stitch.money`, MUST NOT contain `enterprise.stitch.money` |
| Amount correct | link page or mock response | Amount in cents matches `STITCH_PRODUCTS[plan]["price"]` |
| Redirect URL | query string | `?redirect_url=` present and matches `config.STITCH_REDIRECT_URI` |
| Confirmation (mock) | `build_mock_webhook_event(payment_id, status='complete')` fires | C9-PAYCONFIRM arrives with tier upgrade confirmation |
| Failure (mock) | `build_mock_webhook_event(payment_id, status='cancelled')` | C10-PAYFAIL arrives with retry option |

### 10.2 Mock mode handling

The QA run MUST log the `STITCH_MOCK_MODE` value at the top of the payment
section:
```
STITCH_MOCK_MODE=true   → mock confirmation executed end-to-end
STITCH_MOCK_MODE=false  → live flow tested up to payment link only;
                          webhook step flagged LIVE-NOT-EXECUTED
```

If mock mode is on, the report MUST NOT claim "live payment confirmed".

### 10.3 Security checks
- Express credentials only: token endpoint response must say
  `success=true`. Enterprise credentials return a distinctive error — if
  seen, SEV-1 defect.
- Webhook signature: for any webhook-driven confirmation, confirm the
  Svix headers (`svix-id`, `svix-timestamp`, `svix-signature`) are present
  and `stitch.verify_webhook(headers, body)` returns True. Any webhook with
  a failed verify is a SEV-1 defect even if the user-facing message renders.

### 10.4 Scoring band
The payment section contributes to the overall round score as three
distinct cards (C6, C7+C8 bundled, C9 or C10). D1 / D2 / D4 / D5 / D6 apply
per §5. A webhook verification failure forces D1 = 0.0 and automatically
caps the round at FAIL.

---

## 11. Report Format (MANDATORY)

The report MUST follow this skeleton. Any deviation is rejected on review.

```markdown
# QA-BASELINE-NN — <date>

## Environment
- Runtime verified: <output of `ps aux | grep bot.py`>
- Git SHA: <from startup log>
- `STITCH_MOCK_MODE`: <true|false>
- Live odds.db row count: <SELECT COUNT(*) FROM odds_snapshots>
- Profiles used: A (bronze, soccer), B (forced-gold, multi-sport)
- QA commands issued: [list every /qa command sent]

## Navigation Log
<Chronological list of every Telegram interaction. Format:
  HH:MM:SS | <direction in/out> | <artefact type> | <caption_chars> | <buttons>
 e.g.:
  12:03:01 | out | /today | -                     | -
  12:03:03 | in  | C1-DIGEST (HTML text, 1842 ch) | 4 tier filter buttons + pagination>
```

## Per-Card Sections
For each of the ≥ 10 cards:

```markdown
### Card #N — <Card ID per §2.1>
**Navigation path taken:** <literal sequence of commands / taps>
**Card type confirmed:** <C1-DIGEST | C3-EDGEDETAIL | ...>
**Rendered as:** <Photo | HTML text | mixed>
**Screenshot path:** /home/paulsportsza/reports/e2e-screenshots/<run_id>/<card_id>.png
**Caption quote (verbatim):**
> <entire caption text, or "(no caption — photo only)">

**Cross-check evidence:**
| Field | Rendered | DB / expected | Match? |
| --- | --- | --- | --- |
| odds | 2.15 | odds_snapshots row X: home_odds=2.15 @ hollywoodbets | ✓ |
| ...

**Per-dimension scores (with weights applicable to THIS card):**
| Dim | Weight | Score | Evidence summary |
| --- | --- | --- | --- |
| D1  | 30%   | 9.0  | 1 field mismatch, see table above |
| ...

**D7 number cross-check** (C3 / C5 only):
<Two-column verdict-number vs card-display table per §6.5>

**Defects logged from this card:** <defect IDs or "none">

**Card round score (weighted): X.XX**
```

## Onboarding Flow Log
<Per-step log for both Profile A and Profile B. Image vs text classification
per step, button labels, profile persisted to DB confirmed via SELECT>

## Payment Flow Log
<Per-step log for the Stitch flow. `STITCH_MOCK_MODE` noted. Webhook
signature verification outcome>

## Defects Table
| ID | SEV | Card | Defect | Repro steps |
| --- | --- | --- | --- | --- |
| DEF-01 | 1 | C3-EDGEDETAIL Silver | Back button dead-ends | /today → tap Silver filter → tap first pick → tap ↩ → no response |
| ...

## Round Score Calculation
<Show the arithmetic. For each card:
  card_score = Σ(dim_score_i × redistributed_weight_i) for applicable dims
  round_score = mean(card_score for all scored cards)
Show every step. No hand-waving.>

## Visual QA Methodology Statement
<One of:
  "Option A (vision model) used — claude-opus-4-7 describer output
   included verbatim for every D3 score."
  "Option B fallback triggered due to <reason> — D3 excluded from scoring
   for these cards. Human visual QA checklist appended.">

## Coverage Audit
- Cards evaluated: N / 10 minimum
- Onboarding flows: 2 / 2 required
- Sports covered: <list> (≥ 3 required)
- Tiers covered in C3: <diamond|gold|silver|bronze|UNTESTABLE each>
- Payment flow: <executed | skipped-LIVE | blocked>
- Empty states: <list of empty states encountered>

## Verdict
<PASS | CONDITIONAL PASS | FAIL | QA-INVALID>
<Two-sentence justification>

## CLAUDE.md Updates
<Per the constitutional requirement — required updates or "None">
```

---

## 12. Scoring Bands and Pass Thresholds

Round score is the **unweighted mean of per-card weighted scores** across
all evaluated cards (each card is one data point).

| Round score | Verdict | Meaning |
|---|---|---|
| 9.0 – 10.0 | PASS | Shippable. No SEV-1 defects. |
| 7.5 – 8.9 | CONDITIONAL PASS | Shippable with documented carve-outs; 0 SEV-1, ≤ 2 SEV-2. |
| 5.0 – 7.4 | FAIL — regression | Work required before next gate. |
| < 5.0 | FAIL — structural | Design-level rework likely. |

Plus hard overrides (any of these turns the verdict into FAIL regardless of
score):
- Any SEV-1 defect.
- Missing ≥ 1 of the minimum test volume rules in §3.
- D3 scored by imagination (no vision model output AND no UNVERIFIED
  marker).
- D7 scored on a card that is not C3 or C5.
- Verdict not quoted verbatim on any C3 / C5 card evaluated.
- QA agent used `db.set_user_tier()` instead of `/qa set_*`.

And a further auto-flag:
- `QA-INVALID` — runs that violate the anti-fluff rules in §1 are not
  reported as FAIL or PASS. They are reported as QA-INVALID with the rule
  number that was violated, and a new run must be executed.

---

## 13. Pre-flight Gate (Run Before Starting)

Before the QA agent begins any card interaction, the following MUST be
confirmed and logged at the top of the report:

1. **Runtime check** (DEPLOY-DISCIPLINE-1 / D3):
   ```bash
   ps aux | grep bot.py
   ```
   The live path MUST be `/home/paulsportsza/bot/bot.py`. Any other path
   (e.g. `.deploy/…`) → report `ENVIRONMENT NOT CLEAN`, halt run.

2. **Database clean check:**
   ```sql
   SELECT COUNT(*) FROM odds_snapshots WHERE market_type='1x2';
   SELECT COUNT(*) FROM edge_results WHERE DATE(created_at) = DATE('now');
   ```
   Log the counts. If `edge_results` today count is 0, flag that edges may
   not exist for all tiers before proceeding.

3. **Sentry health:**
   ```bash
   tail -n 200 /tmp/bot_latest.log | grep -iE "error|traceback" | head -20
   ```
   Log any fresh errors. If a new P0/P1 error signature appears, escalate
   per the Escalation Rules (CLAUDE.md) before starting the run.

4. **Telethon session check:** confirm
   `/home/paulsportsza/bot/data/telethon_session.string` (or the
   session file in use) authenticates against the QA user.

5. **Confirm `/qa` admin access:** send `/qa profile list` — must return
   the 12 P01–P12 profiles. If "unauthorized", the caller is not in
   `ADMIN_IDS` and this run is invalid.

Only after all five pass may the agent begin card interactions.

---

## 14. Telethon Infrastructure (Build On, Don't Rebuild)

Existing harness files to read before building new ones:
- `bot/tests/w91_p3_telethon_verdict_qa.py` — verdict floor QA, proves the
  photo-to-DB verdict-extraction pattern. Reuse its navigation layers.
- `bot/tests/telethon_verdict_guard_qa.py` — verdict guard suite.
- `bot/tests/e2e_verdict_coherence.py` — coherence enforcement.
- `bot/tests/test_verdict_adversarial_2026_04_15.py` — adversarial set.
- `bot/tests/e2e_telethon.py` — shared connection helpers.

Key patterns to reuse:
- `StringSession` loaded from `data/telethon_session.string`.
- Post-tap verdict reads come from `narrative_cache.narrative_html` keyed
  by `match_id`. The photo card does not carry caption text, so the
  database read IS the verdict of record.
- Button matching uses abbreviated team names
  (`config.abbreviate_team(name, max_len=3)`).
- Inter-tap sleep 1.0s, inter-edge sleep 3.0s (respect bot load).

Any new Telethon scripts written for this rubric must live under
`/home/paulsportsza/bot/tests/qa/` and reuse the existing session +
connection helpers.

---

## 15. Summary — What Good Looks Like

A QA run is excellent when a future Paul can read the report, never open
the bot, and know exactly:
- What the user saw on every card, quoted verbatim.
- What the DB said, cross-referenced line by line.
- Where the product broke, with SEV level and repro steps.
- Why a given dimension scored what it scored, in evidence terms.
- Which tiers / sports / payment states were covered and which were not.

A QA run is broken when:
- A score appears without a quote under it.
- A card type is named that isn't in §2.1.
- D7 is scored on C1, C2, or C4.
- A photo card's D3 score has no vision-model JSON.
- Onboarding or payment is called "passed" without a step-by-step log.
- The report concludes with "looks good".

The whole point of rewriting this rubric is that the previous version
allowed the last one to happen. The rules above make it impossible to do
again without explicitly breaking a numbered rule — which is itself a
SEV-1 defect.

---

## CLAUDE.md Updates
The canonical path `ops/QA-RUBRIC-CARDS.md` is now this rubric. Recommend
CLAUDE.md gain a one-line pointer under the "Verification and Evidence
Rules" section:
> QA rubric: `ops/QA-RUBRIC-CARDS.md` — v3.0 (INV-QA-RUBRIC-OVERHAUL-01).
> Runs that violate the anti-fluff rules in §1 are QA-INVALID regardless
> of score.
