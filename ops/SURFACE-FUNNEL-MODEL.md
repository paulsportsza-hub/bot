# MzansiEdge Surface & Funnel Model — v5.1 (updated 25 April 2026)

> **Authority:** This document is the **canonical, single source of truth** for how every MzansiEdge surface fits into the acquisition → conversion → delivery funnel. It supersedes any conflicting routing, CTA, or content-destination guidance in any other document, memory file, brief, or skill.
>
> If you are an agent (any LLM, any role) and you find a conflict between this document and another file, **this document wins**. File a follow-up brief flagging the conflicting source for cleanup.
>
> **Locked by:** Paul (founder), 20 April 2026, after a 4-iteration session with Edge COO. Versions v1–v4 are superseded.
>
> **Re-read trigger:** Every agent that touches a public surface, a publisher, a CTA, a Bitly link, a generator, an autogen template, an ad creative, or any routing logic MUST re-read this document at session start.

---

## TL;DR — One-Paragraph Mental Model

MzansiEdge runs a five-layer funnel. **Acquisition** is paid Meta ads (Funnel A direct to bot via landing page; Funnel C via WABA 1:1 — Funnel C is BUILDING (MBM verified, CAPI + ad approval pending)). **Discovery** is every public, top-of-funnel surface (WA Channel, IG, TikTok, LinkedIn, Website) — all of these are teaser-only with a single primary CTA driving to Community. **Warming** is the TG Community where users get banter, weekly wraps, premium news posts, polls, free Bronze edges, and Silver content; Community is conversational and engagement-first. **Conversion** is the TG Bot freemium paywall — Bronze free, Gold R99/mo, Diamond R199/mo, Founding Member R699 lifetime. **Delivery** is the private TG Alerts channel (Gold floor, edge-cards-only, no news or banter), with Diamond exclusives delivered via Bot DM. WA Group is dark and waits on Meta BM + WAHA→Cloud API migration. Every public CTA is Bitly-wrapped for per-channel attribution, and any post referencing recent news/results/fixtures must be composed within 30 minutes of publish.

---

## 1. Five-Layer Funnel

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ACQUISITION (paid)                                                      │
│   Meta Ads (R100/day)                                                   │
│     Funnel A (R40/day) ─→ LP /analytics ─→ TG Bot      [LIVE post-LP]   │
│     Funnel C (R60/day) ─→ WABA 1:1       ─→ TG Bot     [BUILDING, CAPI gate] │
│   Every ad creative carries a secondary CTA: → Community [bitly]        │
└─────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ DISCOVERY (public, teaser-only, top-of-funnel)                          │
│   WA Channel (LIVE auto via WAHA) ─────────→ Community [bitly]          │
│   Instagram (Reels + Stories + bio)   ─────→ Community [bitly]          │
│   TikTok (caption + bio)              ─────→ Community [bitly]          │
│   LinkedIn (native posts)             ─────→ Community [bitly]          │
│   Website (banner + /go router)       ─────→ Community [bitly]          │
└─────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ WARMING (public, engaged)                                               │
│   TG Community (@MzansiEdge) — conversational, free, social proof       │
│     • Banter, conversation seeds, polls                                 │
│     • Weekly wraps (Week-in-Review, 4-panel comic images)               │
│     • Premium news posts: previews, signings, recaps                    │
│     • Silver reel videos, free Bronze edges                             │
│     • Pinned + daily CTA → Bot [bitly]                                  │
│     • Bot onboarding Community invite (Paul + LEAD track, separate)     │
└─────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ CONVERSION (freemium paywall via Stitch)                                │
│   TG Bot (@mzansiedge_bot)                                              │
│     Bronze  (free)               → Bronze edges only                    │
│     Gold    (R99/mo)             → Bronze + Silver + Gold               │
│     Diamond (R199/mo)            → everything                           │
│     FM      (R699 once, lifetime) → Diamond equivalent                  │
└─────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ DELIVERY (private, member-only, Gold floor)                             │
│   TG Alerts (@MzansiEdgeAlerts) — PRIVATE                               │
│     • Edge cards ONLY — zero news, zero banter, zero wraps              │
│     • Gold edges    → full pick (all members)                           │
│     • Diamond edges → Gold sees teaser + upgrade; Diamond sees full     │
│     • Bot invites on Stitch subscribe; bot kicks on unsubscribe         │
│   Bot DM → Diamond-exclusive drops (never in Alerts)                    │
│   WA Group → DARK, rewired post-MBM + WAHA→Cloud API migration          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Surface State Matrix

| # | Surface | State | Layer | Primary CTA / Role |
|---|---|---|---|---|
| 1 | Meta Ads — Funnel A | LIVE post-LP | Acquisition | Ad → LP /analytics → Bot |
| 2 | Meta Ads — Funnel C | BUILDING (MBM verified) | Acquisition | Ad → WABA 1:1 → Bot |
| 3 | WhatsApp Channel | LIVE auto (WAHA) | Discovery | Teasers + Top 5 Edges → Community |
| 4 | Instagram Reels + Stories | LIVE | Discovery | Caption + bio router + Story sticker → Community |
| 5 | TikTok (@heybru_za) | LIVE | Discovery | Caption + bio router → Community |
| 6 | LinkedIn | LIVE | Discovery | Native post → Community |
| 7 | Threads | DARK (Decommissioned 25 Apr 2026) | — | Decommissioned |
| 8 | Website (mzansiedge.co.za) | LIVE | Discovery + LP | Pinned banner + /go router → Community |
| 9 | Router page (/go) | TO BUILD | Router | Community / WA Channel / Bot self-select |
| 10 | TG Community (@MzansiEdge) | LIVE | Warming | Discussion + free edges + news → Bot |
| 11 | TG Bot (@mzansiedge_bot) | LIVE | Conversion | Freemium 4-tier |
| 12 | TG Alerts (@MzansiEdgeAlerts) | LIVE (going private) | Delivery | Edge cards only, Gold floor |
| 13 | Bot DM | LIVE | Delivery | Diamond exclusives |
| 14 | WA Group | DARK | Future delivery | Mirrors Alerts post-MBM |
| 15 | WABA Cloud API (Funnel C 1:1) | DARK | Future acquisition | Ad → WABA → Bot |
| — | Superbru | KILLED | — | Decommissioned 20 Apr 2026 |
| — | Facebook Page | KILLED | — | Decommissioned |
| — | X / Twitter | SUSPENDED | — | Appeal pending |

---

## 3. Content-Type Routing (which content goes where)

This table is the law for any publisher, generator, autogen, or scheduled task.

| Content Type | Destination | Notes |
|---|---|---|
| Bronze edge card | TG Bot · TG Community (free pool) | Bot is canonical; Community gets free Bronze pool |
| Silver edge card | TG Bot · TG Community | Visible to Gold+ in Bot; visible to all in Community |
| Gold edge card | TG Bot · TG Alerts (full) | Alerts members see full pick |
| Diamond edge card | TG Bot · TG Alerts (teaser only) · Bot DM (full to Diamond) | Diamond never published in full to a multi-tier surface |
| Top 5 Edges teaser (match + payout, all tiers) | WA Channel | Safe envelope: no team / odds / bookmaker |
| Morning Brief / Evening Intel | WA Channel | Composed T-5min before publish |
| Weekly Wrap (Week-in-Review) | TG Community | Premium news-style, 4-panel comic image |
| Match preview / signing news / recap / poll | TG Community | Conversation seeds |
| Reel card video (B.R.U. drops, 3D card reveals) | IG Reels + TikTok + auto-mirror to IG Story | All CTAs → Community |
| Diary-of-an-AI-Builder post | LinkedIn | Native clickable link → Community |
| Threads native post | — (Threads decommissioned 25 Apr 2026) | Decommissioned — DARK |
| Bot onboarding Community invite | Bot first-run | Paul + LEAD track |
| Member invite / kick | TG Alerts (private) | Triggered by Stitch subscribe / unsubscribe webhook |

**The hard rule:** if a content type is NOT in this table, do NOT publish it. File a follow-up brief to add the row first.

---

## 4. CTA Catalogue (Bitly-wrapped, per-channel attribution)

Every public CTA is wrapped through a per-channel Bitly. Raw `t.me/...` or `mzansiedge.co.za/...` URLs are forbidden in any caption, autogen, or template.

**Minimum 10-wrap set required by launch (27 April 2026):** *(Threads decommissioned 25 Apr 2026 — wrap dropped from 11 to 10.)*

| # | From → To | CTA Copy | Bitly Slug (canonical, audit-confirms) |
|---|---|---|---|
| 1 | WA Channel → Community | `Full Edges On Telegram → [bitly]` | `me-wac-com` |
| 2 | IG → Community | `Full Edges On Telegram → [bitly]` | `me-ig-com` |
| 3 | TikTok → Community | `Full Edges On Telegram → [bitly]` | `me-tt-com` |
| 4 | LinkedIn → Community | `Join the community → [bitly]` | `me-li-com` |
| 5 | Threads → Community | `Full Edges On Telegram → [bitly]` | `me-th-com` |
| 6 | Website banner → Community | `Join the free community → [bitly]` | `me-web-com` |
| 7 | Community → Bot | `Full intelligence → [bitly]` | `me-com-bot` |
| 8 | Alerts → Bot (Diamond upgrade CTA) | `Unlock Diamond → [bitly]` | `me-al-up` |
| 9 | LP → Bot | `Open the bot → [bitly]` | `me-lp-bot` |
| 10 | Meta Ad Funnel A → LP | (campaign URL — wrapped) | `me-ad-a` |
| 11 | Meta Ad Funnel C → WABA | (campaign URL — wrapped, CAPI gate pending) | `me-ad-c` |

**Audit confirms (AUDIT-BITLY-INVENTORY-01):** the actual slugs above are the canonical naming target; the audit reports which exist, which are missing, and which need migration. Once audit lands, this table is updated with real Bitly URLs.

---

## 5. Cross-Cutting Laws

### Law 1 — Bitly enforcement
Every public CTA is Bitly-wrapped through the per-channel attribution table. Raw URLs in captions or templates are forbidden. The publisher reads from the channel_link table in odds.db (built by `BUILD-BITLY-ENFORCEMENT-01`); any caption builder calls the wrapper helper, never hardcoded URLs.

### Law 2 — 30-minute freshness rule
Any post referencing news, results, fixtures, or any time-sensitive fact within the last 24 hours MUST be composed no more than 30 minutes before publish time. Generators that build content earlier than that MUST hand off to the universal `caption_refresh.py` module, which re-binds the news/results/fixture sections at T-5min.

This rule is candidate Standing Order #39, pending the freshness audit (`AUDIT-SCHEDULED-TASKS-FRESHNESS-01`). On audit landing, COO promotes to formal SO.

### Law 3 — Discovery surfaces are teaser-only
WA Channel, IG, TikTok, LinkedIn, Website — none of these surfaces ever publish a full Gold or Diamond edge (team + bookmaker + odds). Safe envelopes:
- **Match + payout** (e.g. "Bangladesh vs Sri Lanka — R150 returns R300") — safe for any tier on any discovery surface
- **Match name + tier badge** — safe
- **Team + odds + bookmaker** — Gold/Diamond ONLY on private Delivery surfaces (Alerts for Gold, Bot DM for Diamond)

### Law 4 — Alerts is edge-cards-only
TG Alerts publishes ONLY Gold and Diamond edge cards. No news. No weekly wraps. No banter. No polls. Anything else routes to Community. Open Alerts, see one thing — picks.

### Law 5 — Single CTA per discovery post
Every public discovery post has ONE primary CTA, driving to Community (via the relevant Bitly). Secondary CTAs only on paid ads (where the secondary CTA also goes to Community, hedging against bot-LP non-conversion).

### Law 6 — IG bio + TikTok bio = router page
The single bio link on IG and TikTok points to `mzansiedge.co.za/go` — a router page that offers Community (primary), WA Channel (secondary), Bot (tertiary). Self-select. All three destinations Bitly-wrapped.

### Law 7 — IG Reel auto-mirror to Story with link sticker
Every IG Reel auto-publishes a companion Story with a clickable link sticker pointing to Community. This is the only clickable IG path that reliably converts; caption + bio are unclickable / single-link respectively.

### Law 8 — Cross-tier protection on Alerts
When a Diamond edge is published to private Alerts:
- Gold members see a teaser (match + tier badge + "Unlock Diamond" CTA → Bitly upgrade link)
- Diamond members see the full pick
- Implementation: tier-aware rendering in the publisher, validated against Stitch subscription state

### Law 9 — Member lifecycle wiring
Stitch webhook fires on subscribe (new Gold/Diamond/FM) → bot generates one-time Alerts invite link → DM to user. Stitch webhook fires on unsubscribe / lapsed → bot kicks user from Alerts. No manual ops in the loop.

---

## 6. What Each Surface Looks Like (Concrete)

### WA Channel — Morning Brief example (post-rewrite)

```
MzansiEdge | Morning Brief

⚽ Last Night
Sc Freiburg 2–1 1 Fc Heidenheim (Bundesliga)
Bayern Munich 4–2 Vfb Stuttgart (Bundesliga)
Aston Villa 4–3 Sunderland (EPL)

📅 Today
Nepal vs UAE — T20I · 13:15
Gujarat Titans vs Mumbai Indians — IPL · 16:00

💡 Today's Top 5 Edges
🥇 Man City vs Arsenal — R200 returns R380
🥈 Bangladesh vs Sri Lanka — R150 returns R300
🥈 Bangladesh vs New Zealand — R100 returns R400
🥉 Nepal vs UAE — R100 returns R220
🥉 Gujarat vs Mumbai — R150 returns R270

Full Edges On Telegram → [bitly]/community

18+ · Play Responsibly
```

**Notes:** single CTA. Top 5 includes all tiers (match + payout safe). News block bound at T-5min. No duplicate CTA.

### TG Community — what flows here

Currently flowing in (already correct): conversation seeds, polls, banter.
Migrating in from Alerts: Week in Review, premium news posts (4-panel comic images), match previews, signings, recaps.
Adding: Silver reel videos, free Bronze edges, daily "5 edges in the bot" hook with link to Bot.

### TG Alerts — what flows here (post-private flip)

Only edge cards. Gold full. Diamond teaser-with-upgrade for Gold members; full for Diamond members. That's it.

---

## 7. Migration Brief Stack (post-lock execution)

**Wave 1 — Audits (parallel, fire on lock)**
- `AUDIT-BITLY-INVENTORY-01` — Opus Max Effort - AUDITOR — enumerate existing MzansiEdge Bitly links, map to channel, flag gaps
- `AUDIT-SCHEDULED-TASKS-FRESHNESS-01` — Opus Max Effort - AUDITOR — enumerate every cron + scheduled task on server + Cowork; output (a) freshness matrix RED/AMBER/GREEN, (b) destination map per task

**Wave 2 — Builds (parallel, gated on Wave 1 returns)**
- `BUILD-BITLY-ENFORCEMENT-01` — channel_link table + publisher integration + caption builder helper
- `BUILD-CAPTION-REFRESH-UNIVERSAL-01` — extend `caption_refresh.py` to all flagged generators
- `BUILD-WA-CHANNEL-REWRITE-01` — Top 5 Edges payout format + single CTA + duplicate-CTA bugfix + Bitly wrapping
- `BUILD-ALERTS-PRIVATE-01` — flip Alerts to private channel; bot invite/kick on Stitch subscribe/unsubscribe
- `BUILD-PUBLISHER-CONTENT-ROUTING-01` — content-type axis (news → Community, edge → tier-routed) + tier axis (Gold → Alerts full, Diamond → Alerts teaser + Bot DM full)
- `BUILD-COMMUNITY-TRAFFIC-LAUNCH-01` — website banner + standardised social end-card + paid ad secondary CTA
- `BUILD-BIO-ROUTER-PAGE-01` — `mzansiedge.co.za/go` router page
- `BUILD-IG-STORY-MIRROR-01` — auto-mirror every IG Reel to Story with link sticker → Community

**Wave 3 — Doc lock (final, after all builds land)**
- `DOC-MODEL-V5-LOCK-01` — this document is the spec; sweep all other docs for conflicts (handled by COO directly, not dispatched)

---

## 8. Where This Document is Referenced

Any doc, memory file, brief, or skill that touches surfaces, CTAs, routing, or content destinations MUST link back to this file rather than duplicate the content. Known referencing files (kept in sync):

- `CLAUDE.md` — Ops Modules table + Quick Reference
- `ME-Core.md` — Pillar 5 (Marketing & Acquisition)
- `ops/MARKETING-CORE.md` — supersedes per-channel routing in §1–§3
- `ops/MARKETING-ROADMAP.md` — surface index
- `COO/PAID-ADS-ROADMAP.md` — Funnel A/C routing + secondary CTA
- `COO/STATE.md` — current surface states
- `COO/ROUTING.md` — channel routing
- `.auto-memory/product_architecture.md` — surfaces section
- `.auto-memory/channel_publishing_pipeline.md` — destinations + content-type routing
- `.auto-memory/project_surface_funnel_model_v5.md` — local cache pointer
- Notion: Core Memory · Active State · Product Technical Reference

---

## 9. Version History

- **v5.1 — 25 April 2026** — Threads decommissioned (was LIVE Discovery); Funnel C / WABA state shifted from DARK to BUILDING / LIVE-webhook (Meta Business Manager verified, WhatsApp templates approved, Cloud API webhook live per WA-CLOUD-API-01 commit 2026-04-24). Remaining Funnel C gates: BUILD-CAPI-01 + ad campaign approval. Bitly wrap set drops 11 → 10.
- **v5 — 20 April 2026** — LOCKED. Adds IG Story link sticker, bio router page, content-type axis routing for Alerts vs Community split (Alerts = edge cards only, all news/wraps/premium → Community), Bitly enforcement law, 30-min freshness law, Top 5 Edges payout framing for WA Channel, single driving CTA `Full Edges On Telegram → [bitly]`. Supersedes v1–v4. Superbru wiped.
- **v4 — 20 April 2026 (intermediate)** — Added Alerts content-type clarification (edge cards only).
- **v3 — 20 April 2026 (intermediate)** — Added Top 5 Edges payout framing and single driving CTA.
- **v2 — 20 April 2026 (intermediate)** — Added WA Channel + Alerts gating, Diamond → Bot DM separation.
- **v1 — 20 April 2026 (intermediate)** — Initial integrated diagram from segmentation question.

---

*End of canonical spec. If you are an agent reading this and have any uncertainty about how a surface fits into the funnel, stop and ask. Do not guess.*
