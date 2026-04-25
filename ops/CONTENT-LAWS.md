# Content Laws & Publishing Rules

> **Source of truth for all content laws, platform-specific rules, publishing flow, fact-check system, and queue management.** Referenced from CLAUDE.md. All agents producing content must read this file.

*Last updated: 17 April 2026 PM by AUDITOR (CLAUDE-MD-SO-SPLIT-01 Tier 1 — absorbed 9 SOs from CLAUDE.md: #3, #8, #17, #21, #22, #23, #24, #26, #34.)*

---

## Standing Orders (moved from CLAUDE.md — 17 April 2026 PM)

*Original SO numbers preserved for historical reference. All agents producing ANY content (copy, social posts, emails, Notion pages, image prompts, outreach lists) must read and re-read these before every response.*

- **[SO #3]** Skills gate all scheduled content — manual approval is deprecated. (UPDATED 17 Apr 2026.) The skill library (`brand-voice-dna`, `evidence-gate`, `verdict-generator`, `telegram-news-post`, `nb2-image-gen`, `haiku-match-summary`) enforces brand, evidence, verdict quality, fact-checks, and format at generation time. `Status=Approved` in Marketing Ops Queue means skill-validated, not human-reviewed. Publisher fires the 3h cron on anything queued. Exception: founder-voice content (personal LinkedIn posts, press, direct comms) still requires Paul's explicit greenlight. If a content surface lacks a skill gate, add the skill — never add a human review step.
- **[SO #8]** Read Copywriting DNA before writing or generating ANYTHING. `reference/COPYWRITING-DNA.md` is mandatory reading before producing any copy or any image prompt. No exceptions.
- **[SO #17]** Approval = Queue immediately. Publisher picks it up. When Paul approves any content, the COO MUST — in the same response — create the Marketing Ops Queue item with all required fields. The Python publisher runs every 3 hours.
- **[SO #21]** Fact-check before finalising any content with specific claims (L1 gate). See the full fact-check system elsewhere in this file.
- **[SO #22]** Never write a URL that hasn't been verified to exist. Any URL written into a Notion page, brief, social post, email, or any user-facing surface MUST return HTTP 200 before being written.
- **[SO #23]** Zero placeholders ship to Paul. Ever. No page may contain placeholder text in brackets, "TBD", "pending research", or any incomplete marker.
- **[SO #24]** Verify all named people before including them in outreach lists. Every person must be verified as alive, active, and in the role claimed.
- **[SO #26]** Approval items must include direct media preview links. Format: `[▶️ Watch video](URL)` or `[🖼️ View image](URL)`.
- **[SO #34]** Social content positioning — MzansiEdge is a sports intelligence platform, not a gambling operator. (LOCKED 13 Apr 2026.) Never use betting/gambling language in social captions on discovery channels. No odds, no bookmaker names, no stake/payout amounts, no "Bet Responsibly", no NRGP footer, no 18+ disclaimer on IG/TikTok/WhatsApp Channel/Facebook/LinkedIn — these hurt algorithmic reach and are NOT legally required (NGA applies to licensed operators only, not tipster/analytics services). Telegram and WhatsApp group (closed community, opted-in users) use `"18+ · Play Responsibly"` only. Caption framing: edge scores, match intelligence, sports analytics. Implemented in `publisher/compliance_config.py` (SOCIAL-POSITIONING-01) and `publisher/channels/tiktok.py` (REEL-PIPELINE-MASTER-01, TIKTOK-CAPTION-01).

---

## Content Laws (MANDATORY — zero tolerance)

### Law 1: Brand Accuracy

Every piece of content must be audited against the UVP before delivery. No exceptions.

**Locked language rules:**
- **Product scope:** Cross-references odds, player form, injury data, tipster consensus, and match conditions. All five layers in any product description. Never deny or omit any.
- **Bookmaker reference:** Always "all major SA bookmakers." Never a specific number.
- **Edge tiers:** 💎 Diamond, 🥇 Gold, 🥈 Silver, 🥉 Bronze. Never "Platinum." Never "Golden." Never ⛏️ mining pick.
- **Sports:** Soccer, Rugby, Cricket, Boxing, MMA. Never horse racing or F1.
- **SA English:** realise, favour, analyse, colour.
- **"Edge" is a word-mark:** Always capitalise "Edge" when referring to our product concept (e.g. "Diamond Edge," "find your Edge," "7 Edges live right now," "Edge alert"). Only lowercase when used as a generic English word not referring to MzansiEdge's product (rare). This applies to ALL content: website, social, briefs, Notion, docs.
- **No guarantees:** Never promise wins or profits. Use "Edge," "value," "expected value."
- **Responsible gambling:** Never oversell. Honest about risk.

### Law 2: Pre-Delivery Audit

Before any content is delivered or published: (1) verify product description matches UVP, (2) check tier names/sport references/spelling, (3) confirm no win/profit guarantees, (4) verify "all major SA bookmakers" language, (5) ensure responsible gambling tone, (6) flag contradictions — fix before delivery.

### Bitly Link Law (LOCKED — 9 March 2026)

All Act 2+ social posts MUST use channel-specific Bitly links (custom domain: go.mzansiedge.co.za):
- X/Twitter: `go.mzansiedge.co.za/4u0Vh3b`
- Facebook: `go.mzansiedge.co.za/site-fb`
- Instagram: `go.mzansiedge.co.za/site-ig`
- LinkedIn: `go.mzansiedge.co.za/site-li`
- TikTok: `go.mzansiedge.co.za/site-tt`
- Telegram Bot CTA: `go.mzansiedge.co.za/47fC1oO`
- WhatsApp Channel Join: `go.mzansiedge.co.za/join-wa`
- WhatsApp (site traffic): `go.mzansiedge.co.za/site-wa`

Act 1 posts (no product reveal) = no link needed. Blog/website internal links can use direct URLs.

**LinkedIn exception (LOCKED — 20 March 2026):** LinkedIn posts ALWAYS use `go.mzansiedge.co.za/site-li` — even in Act 1 — because the LinkedIn mandatory link rule requires a link on every post. Never use the raw `mzansiedge.co.za` URL on LinkedIn. The Bitly link redirects to the same destination (preserving the SEO backlink) AND gives us click tracking. Raw URLs = blind spots.

### LinkedIn Laws (LOCKED — 11 March 2026)

**LinkedIn Post Strategy — Profile Building Phase, 4-pillar (LOCKED — 7 April 2026, supersedes the Investor-Focused 5-Pillar interim):**

Canonical reference: memory `feedback_linkedin_strategy.md`. The full Investor-Focused strategy doc (`reference/INVESTOR-LINKEDIN-STRATEGY.md`) is **selectively applied** — frame + profile + pillars + cadence + voice are kept; outreach machinery, watchlist verification, legal consultation, and soft-signal language are TABLED until post-traction.

**Why Profile Building, not investor outreach:** Paul audible 7 Apr — investor outreach is premature with no working product and no incorporation. Goal is to build an AI-infrastructure founder profile over time so that when the fundraise conversation eventually happens (3–6 months of real traction), the profile already reads the part. Zero compliance risk, zero wasted cycles on premature investor DMs.

**The frame (non-negotiable):** Paul is an **AI-infrastructure founder**, NOT a tipster. Every LinkedIn post lands MzansiEdge as "Africa's sports intelligence layer." Analogues: Bloomberg/finance, Sportradar/sports data, OddsJam/betting intelligence. NEVER use "gambling", "tipster", "picks" on LinkedIn. Primary audience: **SA tech founders, AI builders, journalists, operators, potential customers**. Investors will discover the profile organically post-traction — they are NOT the primary audience today.

**4 pillars (ratio-weighted):**

| Pillar | Frequency | Purpose |
|---|---|---|
| 1. AI dev methodology (Diary of an AI Builder) | 1×/wk | Paul's native voice. Multi-agent Claude Code lessons. Technical authority. |
| 2. SA betting market intelligence | 1×/wk | Niche-authority slot. "MzansiEdge knows this category." |
| 3. Traction + milestones | 1×/2wk (starts once there's traction) | Soft momentum signal |
| 4. Founder journey / lessons | 1×/2wk | Relatability, lightweight |

**Pillar TABLED (was #4 in the interim version):** International comparables (OddsJam $160M, Action Network $240M, Sportradar $5B, Sharp Alpha fund). No longer a regular rotation slot — that was investor-anchoring framing. May surface sparingly as context inside market-intel posts, but no relentless anchoring.

**Pre-launch (8–27 Apr) = MINIMAL — two actions only:**
1. Profile rewrite v1 (entity-safe headline + About, already drafted — Paul approves + manually updates)
2. ONE launch-countdown tease post in week of 20 Apr

No pillar rotation, no engine, no silent connects, no event registration, no legal consultation pre-launch. Paul is resource-locked on the launch gate per SO #13.

**Post-launch (28 Apr onwards):** 3×/wk cadence — Tue/Wed/Thu 15:00–17:00 SAST. Format rotation carousel → text+image → text-only. PDF carousels (6–9 slides) lead engagement at ~7% per 2026 data — Pillar 1 defaults to carousels. Pillar 3 and Pillar 4 work as text-only. Hook discipline: 2 lines max before the "see more" fold. Stat-first opening wins. Voice always from `reference/COPYWRITING-DNA.md` (SO #8).

**Post generation flow:** COO generates topic ideas + interview questions based on which pillar is due → Paul answers in voice memo or text dump → COO writes post in Paul's voice using Copywriting DNA → Paul approves → COO queues to Marketing Ops Queue per SO #17.

**Daily 15-min engagement ritual (from 28 Apr):**
- Comment substantively (25+ words) on 3 posts from **SA tech / AI / operator targets** (NOT investors)
- Reply to all comments on Paul's own posts
- Add 2–3 personalised connection requests (no pitch)
- Posting and engaging are SEPARATE time blocks — do not post during the ritual

**TABLED until post-traction (revisit once MzansiEdge has 3–6 months of real traction):** Investor Tier 1/2 watchlist verification, 4-stage outreach sequence (silent connect → authority → DM → meeting), legal consultation (ENSafrica/Webber Wentzel/CDH) on FSCA soft-signal compliance, profile v2 investor-facing paragraph, Pillar 4 comparables as regular rotation, 12-week investor KPI tracking, event registrations (AfricArena Dec, AESI Nov — October calendar reminder), LinkedIn Premium Business, incorporation urgency (still needed eventually, not a pre-launch gate).

**Status 7 Apr 2026:** LinkedIn is in Profile Building Phase per SO #13 — launch gate is the one live priority. Pre-launch = profile rewrite + 1 countdown post. Full 4-pillar engine spins up 28 Apr.

**LinkedIn character limit (LOCKED — 20 March 2026):** LinkedIn API truncates posts at ~3,000 characters with NO warning. Every LinkedIn post MUST be under 2,800 characters (safe buffer). Count characters BEFORE creating the queue item. If over limit, trim — never publish and hope.

**Mandatory link rule (LOCKED — 20 March 2026):** Every LinkedIn post MUST include `go.mzansiedge.co.za/site-li` — either in the post body or as a first comment. No exceptions. This gives us both the SEO backlink AND Bitly click tracking. Never use the raw `mzansiedge.co.za` URL on LinkedIn.

**Connection messages:** ≤200 characters (hard LinkedIn limit). Every message deeply personalised — must reference something specific about the person's profile. Generic "keen to connect" messages are BANNED.

**Connection Message Quality Rules (LOCKED — 19 March 2026):**
1. **First person always.** "I'm building..." not "Building...". These are from Paul, a human. They must read like a DM from a real person.
2. **Reference something SPECIFIC and UNIQUE** about them — a particular achievement, career move, company milestone, or opinion they shared. NOT just their job title restated.
3. **Never use these dead phrases:** "Would value connecting", "Keen to connect", "Would love to connect", "Would be great to connect", "Would welcome your perspective". These are robotic filler. End with something human instead — a question, a specific compliment, or a direct statement.
4. **The test:** Read it aloud. If it sounds like a bot wrote it, rewrite. If you could swap the name and it would work for anyone else in that industry, rewrite. The message must ONLY work for that one specific person.
5. **Good endings:** "Thought you'd find it interesting.", "Similar orbit — would be good to compare notes.", "Your [specific thing] caught my eye.", or just end after the compliment — no explicit "connect" ask needed.
6. **MzansiEdge mention:** Keep it to one short clause. "I'm building MzansiEdge — AI that finds mispriced odds across SA bookmakers." Never more than this. The message is about THEM, not us.

**Bad example:** "Gayle — from DigiOutsource operations to running Lead Capital across gambling, fintech and crypto is a powerful pivot. Building an AI product for SA bettors. Would love to connect."
**Why it's bad:** "Building" not "I'm building". "Powerful pivot" is generic flattery. "Would love to connect" is dead phrase. Could work for anyone who changed jobs.

**Good example:** "Gayle — scaling Lead Capital across three verticals after DigiOutsource is no small feat. I'm building MzansiEdge, AI that spots mispriced odds across SA bookmakers. Gambling meets AI — thought our worlds overlap."
**Why it's good:** First person. Specific (three verticals, DigiOutsource named). No dead phrases. Ends with a human observation, not a request.

**Positioning exemplar (LOCKED):** When messaging people at bookmakers (Betway, Hollywoodbets, Sportingbet, etc.), NEVER position MzansiEdge as adversarial or competitive to their business. We are NOT a competitor to bookmakers. We help bettors navigate the market — we're a complement to the ecosystem, not a threat.
**Bad:** "I'm building MzansiEdge to show bettors when your odds are wrong." (adversarial — positions us against them)
**Good:** "I'm building MzansiEdge, AI that helps bettors compare prices across the market. Thought you'd find the data angle interesting." (complementary — positions us as a market tool)

**Format in Notion Task Hub:**
```
- [ ] ⭐ **Name** — Role, Company — [LinkedIn](url)
   - 💬 *Specific, human message referencing something real about them. ≤200 chars.*
```

**LinkedIn Connection Ledger:** Every run must check the ledger (`320d9048-d73c-818d-8c7e-c4d06d1e3461`) before generating targets. Parse `SLUG_INDEX_START`/`SLUG_INDEX_END` code block. Skip duplicates. Append new slugs after generating targets.

### Facebook Group Laws (OVERHAULED — 16 April 2026)

All agents generating FB group posts MUST use verified URLs from the tables below. Never guess or construct URLs. **Posts are published from the MzansiEdge page** (not Paul's personal profile).

**Strategy shift (16 Apr 2026):** Content Library audit (19 Mar–15 Apr, 50 posts) proved: only rugby groups generate engagement. All generic PSL/Betway groups, cricket groups, and MMA groups produced zero interactions. The new strategy is team-specific fan groups with team-specific content — not generic league posts sprayed across generic groups.

**Frequency rule (LOCKED 16 Apr 2026):** 2 posts per group per week maximum. Rotate which groups get posts each day. No group sees MzansiEdge content two days running. Daily output: 4–6 posts/day across all groups.

**Phased attribution approach:**
- **Established groups (rugby):** Full attribution line: `📊 Find your edge → mzansiedge.co.za` on every post.
- **New groups (football — first 4 weeks):** Pure value only. NO attribution line, NO links, NO MzansiEdge mentions. Earn reputation first. After 4 weeks with consistent engagement, graduate to soft attribution.
- **Soft attribution (weeks 5–8):** Single natural mention woven into content: "Analytics tools like MzansiEdge track this kind of pricing shift." Once per week per group max.

**Post format (UPDATED 16 Apr 2026):** Posts include an NB Pro image + copy generated via `fb-group-post` skill. The skill enforces brand voice, engagement framing, and team-specific relevance.

1. **Image:** 1080×1080 NB Pro image. Team-specific when possible (team colours, player references, crest-adjacent). Hosted on WordPress. Never catbox.
2. **Copy structure (write to Notion as code block with `\n\n` between paragraphs):**
```
[EMOJI] [PUNCHY HEADLINE IN ALL CAPS — ≤80 chars]

[Lead insight — team-specific, opinionated, discussion-starting. 2-3 sentences.]

[Supporting detail — stat, contrast, or consequence. 2-3 sentences.]

[Sharp question or take that invites replies.]

[Attribution line — ONLY for established groups, see phased rules above]
```

**CODE BLOCK RULE (LOCKED 7 Apr 2026 — NEVER REGRESS):** All copy in Notion MUST be in triple-backtick code blocks with `\n\n` between paragraphs for clean Facebook paste.

**Headline character limit (LOCKED):** ≤80 characters including emoji and spaces. Count programmatically.

**Tournament/event reference rule (LOCKED):** Never frame an event as upcoming without verifying it hasn't occurred.

**Content approach — fan engagement, not fan impersonation:** We don't pretend to support the team. We provide intelligence that fans value: form analysis, transfer impact, head-to-head data, tactical breakdowns, match previews with a data lens. Frame: "Here's what the data says about your team this week." Not: "Let's go Chiefs!"

**SO #34 compliance:** Sports intelligence framing only. No betting language, no odds, no bookmaker names, no stake/payout amounts on FB groups (discovery channel).

#### Tier 1 — Rugby (PROVEN — post 2x/week each, full attribution)
Content Library confirmed: these 4 groups are the only ones generating real engagement (up to 8,563 views and 45 interactions per post).

| Group | Members | URL | Notes |
|-------|---------|-----|-------|
| Total Rugby | 84.7K | `https://www.facebook.com/groups/817532796900989/` | Best performer: 4,055 views, 45 interactions top post |
| Rugby 🇿🇦🏆 World Cup Champions | 81.8K | `https://www.facebook.com/groups/worldcupchampions/` | Strong: multiple posts, 30 interactions best |
| Springbok Supporters Group World Cup 2027 | 70K | `https://www.facebook.com/groups/269900239689473/` | Highest reach: 8,563 views, 22 interactions |
| GREEN & GOLD SPRINGBOKS | 50.2K | `https://www.facebook.com/groups/236596381055720/` | Moderate: 1,368 views, 7 interactions |

#### Tier 2 — PSL Fan Groups (NEW — team-specific content, no attribution first 4 weeks)
Replace generic Betway Premiership groups (which got 0 interactions) with team-specific fan groups. These are massive, highly active communities. Content MUST be team-specific.

| Group | Members | URL | Team | Content Focus |
|-------|---------|-----|------|---------------|
| Real Kaizer Chiefs Supporters | 1.2M | `https://www.facebook.com/groups/494611591148003/` | Chiefs | Chiefs form, transfers, match previews, player analysis |
| Orlando Pirates News | 2.1M | `https://www.facebook.com/groups/407362666620556/` | Pirates | Pirates form, CAF campaign, signings, tactical shifts |
| MAMELODI SUNDOWNS F.C FANS NEWS AND UPDATES | 538K | `https://www.facebook.com/groups/1654828004797590/` | Sundowns | Sundowns dominance data, CAF stats, depth analysis |

#### Tier 3 — EPL Fan Groups (NEW — team-specific content, no attribution first 4 weeks)
Global fan groups with massive African membership. Paul's team (Man United) gets priority. Content must be team-specific and data-driven.

| Group | Members | URL | Team | Content Focus |
|-------|---------|-----|------|---------------|
| Manchester United fans Africa | 68K | `https://www.facebook.com/groups/1479191376852513/` | Man United | Africa-specific, Paul's team — highest priority EPL group |

**EPL Recruitment Targets — Paul to join from MzansiEdge page, then add URLs here:**

| Group Name | Members | Team | Search Term |
|------------|---------|------|-------------|
| MANCHESTER UNITED FANS | 1.4M | Man United | "MANCHESTER UNITED FANS" — Public, 90+ posts/day |
| ARSENAL TRANSFER NEWS, LIVESCORES AND UPDATE | 1.2M | Arsenal | "ARSENAL TRANSFER NEWS" — Public, 90+ posts/day |
| LIVERPOOL FC FANS | 894K | Liverpool | "LIVERPOOL FC FANS" — Public, 90+ posts/day |
| Chelsea Football Club Worldwide Fans | 705K | Chelsea | "Chelsea Football Club Worldwide" — Public, 90+ posts/day |
| All Soccer News Updates | 1.3M | General PSL | "All Soccer News Updates" — Public, Betway branding |
| PREMIER LEAGUE RESULTS AND FIXTURES | 529K | EPL General | "PREMIER LEAGUE RESULTS AND FIXTURES" — Public |
| UEFA Champions League 2025-2026 | 320K | UCL | "UEFA Champions League 2025-2026" — Public |

**Recruitment protocol:** Search each group name on Facebook → Join as MzansiEdge page → Verify post lands within 24h → Add URL to Tier 3 table above → Remove from recruitment list.

#### Killed Groups (16 Apr 2026 — zero engagement confirmed via Content Library)
These groups are permanently removed. Do NOT reactivate without Paul's explicit approval.

| Group | Reason |
|-------|--------|
| BetWay Premiership 2024/2025 (82.8K) | 0 interactions across all posts |
| South Africa PSL - Betway Premiership (200K) | 0 interactions across all posts |
| Betway Premiership - South Africa PSL (143K) | 0 interactions across all posts |
| The Rugby Punt-it (19.6K) | Removed — betting-focused group, SO #34 conflict |
| JUST PLAIN RUGBY (9.9K) | Too small, no measurable engagement |
| Football Development in South Africa (84K) | 0 interactions |
| South Africa Cricket Supporters (44.7K) | 0 interactions, 0–1 views |
| MMA South Africa (39.2K) | 0 interactions outside fight weeks |
| BAFANA BAFANA NEWS UPDATE (48.6K) | Posts stuck in admin review |
| All Tier 4 fan groups from 7 Apr | Never verified, replaced by larger groups above |
| Springboks vs the World (114.9K) | Blocked — posts stuck in pending |
| South Africa Cricket Team (160K) | Blocked — posts never published |

#### Daily Rotation Target — 4–6 posts/day (UPDATED 16 Apr 2026)

| Category | Groups active | Posts/week | Daily average |
|----------|--------------|------------|---------------|
| Rugby (Tier 1) | 4 | 8 (2/group) | ~1/day |
| PSL Teams (Tier 2) | 3 | 6 (2/group) | ~1/day |
| EPL Teams (Tier 3) | 1 active + 7 recruiting | 2+ (2/group) | ~1/day growing |
| **Total** | **8 active** | **16+/week** | **~4–6/day** |

As EPL recruitment targets are joined and verified, daily output grows toward 8–10/day.

**Posting spread:** Paul posts FB group content in one batch. No timed spreading required.

**Content rules:** Match team to group. Chiefs content in Chiefs groups only. Pirates in Pirates groups. Springbok content in rugby groups. Every post must be team-specific and independently valuable. No cross-team mismatches. Generic "PSL round-up" posts are banned — always pick a team angle.

### Quora Laws (LOCKED — 21 March 2026)

**Frequency:** Daily. 5 fresh questions per day, every day. Scheduled task: `daily-quora-pipeline` runs at 07:00 SAST.

**Pipeline:** Scheduled task searches Quora for 5 new high-traffic questions → checks ledger for duplicates → writes expert answers → creates batch page under Project Memory → appends URLs to ledger. Paul copy-pastes answers to Quora manually.

**Delivery location:** Each daily batch is a standalone page under Project Memory (`313d9048-d73c-818f-94aadea85b5158d0`), titled `📝 Quora Daily — [date] (5 Questions)`. **NOT** in Paul's Task Hub. Task Hub only gets a one-line reminder if needed.

**Mandatory link rule (LOCKED — 19 March 2026):** Every Quora answer MUST include a natural mention of `mzansiedge.co.za` — e.g. "Tools like MzansiEdge (mzansiedge.co.za) automate this comparison across all major SA bookmakers." This is critical for SEO backlink building. The mention must feel natural, not spammy — one per answer, woven into the educational content.

**Format (LOCKED — 21 March 2026):** Each question uses this structure: `## Q[n]` heading → Priority tag → URL link → `<details><summary>Copy-Paste Answer</summary>` toggle with full answer → `- [ ] Posted` checkbox. This is the approved format Paul wants — URL visible, answer in dropdown, checkbox for tracking.

**Quora Answered Ledger (LOCKED — 21 March 2026):** Ledger lives at `320d9048-d73c-8109-bc66-ddf2c9ab5fe8`. Contains machine-readable `URL_INDEX_START`/`URL_INDEX_END` code block + human-readable table. Every run: (1) fetch ledger, (2) parse ALL URLs from index, (3) reject any question whose URL matches, (4) after writing batch, append new URLs to index + table. **The #1 failure mode is duplicate questions. Triple-check every URL against the index before accepting it.**

**Old task:** `quora-reddit-posting` (Mon/Thu) is DEPRECATED and disabled. Replaced by `daily-quora-pipeline` (daily 07:00 SAST).

### Community Platform Laws (LOCKED — 28 March 2026)

**Three owned community channels for organic SA audience building pre-launch.** All require Paul to post manually — cannot be automated. COO scans daily for opportunities and delivers ready-to-post content to TASKS.md via `community-hub-patch` task (runs 30 min after each `pauls-task-hub` rebuild at 06:30, 09:30, 12:30, 15:30, 18:30, 21:30 SAST).

**Daily scan tasks:** `daily-reddit-scan` (07:15 SAST), `daily-mybroadband-scan` (07:45 SAST), `daily-superbru-scan` (09:15 SAST). Each creates a Notion page under Project Memory (`313d9048-d73c-818f-94aadea85b5158d0`) titled with emoji + platform + date. Pages are injected into TASKS.md by `community-hub-patch`.

**Paul's daily commitment:** Superbru 5 min/week. Reddit and MyBroadband are PAUSED until post-launch — not needle movers while all capacity goes to the four pillars (ME-Core.md).

**Access note (for when Reddit/MyBroadband resume post-launch):** reddit.com is blocked from WebFetch AND Chrome extension — use WebSearch only for Reddit scanning. MyBroadband and Superbru are accessible via WebFetch.

#### Reddit (Account: PaulSports_ZA)

**Act 1 (pre-launch, to 30 Mar): Comment-only.** Pure value contributions. Zero self-promotion. Build karma first.

**Target subreddits:**

| Subreddit | Members | Purpose |
|-----------|---------|---------|
| r/southafrica | 257K | Primary — SA general. Sports/betting/data angles. Transparent founder identity OK post-launch. |
| r/rugbyunion | 439K | Rugby discussions. SA team analysis, URC, Boks results. Match threads go live on game day. |
| r/sportsbetting | 274K | Betting discussions. EV/value betting education only. |

**Rules:**
- r/southafrica banned X/Twitter links (Jan 2025). Never link to X content.
- No MzansiEdge mentions until Act 2+ (31 Mar+).
- Comment as a knowledgeable SA sports/betting fan.
- r/springboks (13K) — dormant (1 post/24 days). Skip for now.
- Match threads in r/rugbyunion go live on game day — primary real-time opportunity.

**Act 2+ (31 Mar+):** One subtle MzansiEdge mention per week where genuinely relevant. Never forced.

**Launch post (27 Apr):** Full "I built this" founder story post on r/southafrica. COO drafts by 20 Apr for Paul review.

**Post-launch:** Create r/SAbetting as owned SA sports betting community (first-mover advantage). Timing: 2-4 weeks after 27 Apr once first users are active. Account needs karma first.

#### MyBroadband (Account: PaulDomanski — transparent founder identity)

Profile openly identifies Paul as MzansiEdge founder. Posts always reflect this openly.

**Primary targets:**

| Thread | URL | Status |
|--------|-----|--------|
| Sports Betting | `mybroadband.co.za/forum/threads/sports-betting.1324318/` | Dormant since Oct 2025 — revive with pure sports opinion (no odds/product angle until Act 2+) |
| Sports Forum Index | Verify URL manually — previous URL was 404ing | Navigate mybroadband.co.za → Forums → Sports |

**Rules:**
- Max 3 posts/week total. Spread across different days.
- Reply to existing threads only in Act 1. No new threads until Act 2+.
- Transparent founder identity always. Never hide.
- **Content direction (Act 1 — LOCKED 29 March 2026):** Pure sports authority. No odds, no EV/margin analysis, no bookmaker references, no product angle. Build credibility as a genuine SA sports fan who knows the game deeply — same approach as Reddit. Once the community knows Paul as a knowledgeable voice, the product angle lands naturally in Act 2+.
- No external links in Act 1.
- MMA thread (~407K views): activate fight weeks only. Cricket/Rugby: major SA fixture days.

**Paul's voice and allegiances (use to personalise every post):**
Paul follows SA sport closely and is personally invested. Always write from this perspective, not as a neutral analyst:
- **Rugby:** Stormers are his team. SA provincial sides generally (Bulls, Lions, Sharks too — but Stormers first). Springboks are a genuine passion.
- **Cricket:** Proteas.
- **Football:** Man United (English PL). Bafana Bafana for SA national fixtures.
- Opinions should reflect real fan investment — frustration, pride, specific observations from the match. Never neutral. Never "both sides have merit."

**Tone benchmark (LOCKED — 29 March 2026):** Paul's reply on the URC four-from-four thread is the target voice:
> "Four from four for SA! Bulls beating Munster 34-31 was the standout for me. Munster are never easy regardless of venue, and SA sides historically grind through those European away fixtures. Bulls held their nerve when it mattered. Stormers were the most clinical — their defence has been the most consistent of the SA sides this season."

Why it works: personal ("for me"), specific match detail, genuine opinion ("most clinical"), no padding, reads like a human fan not an analyst. Every MyBroadband reply must meet this standard.

**Formatting rules (LOCKED — 28 March 2026 — learned from Heisenborg's "#34 They are called paragraphs" response):**
- **Paragraph breaks are mandatory.** Every distinct point or idea gets its own paragraph with a blank line between. No walls of text. Ever.
- **No inline numbered lists.** Writing `(1)... (2)... (3)...` inside a single paragraph is an AI tell. Use separate paragraphs, or if numbered structure is genuinely needed, put each on its own line.
- **Short, direct sentences.** MyBroadband tone is blunt and opinionated, not academic. Write how a knowledgeable person talks, not how an essay is structured.
- **No AI sentence openers.** Avoid: "X is actually three separate questions most people conflate", "It's worth noting that", "The reality is", "In essence". These are AI patterns that veterans recognise instantly.
- **Read it back before finalising.** If it looks like a block, it IS a block. Break it up.
- **MyBroadband members are sharp.** This is a tech-literate SA community with senior members who have 10K–20K+ posts. They will call out bad formatting and AI-sounding language immediately and publicly.

#### Superbru (MzansiEdge Club — CREATED 29 March 2026)

**Club URL:** https://www.superbru.com/club/mzansiedge ✅

**Club benefits active:** Permanent superbru.com page, banter board (community chat wall for live match commentary), newsletter to Club members, ability to create Club pools.

**Next action — create Club pools (Paul does this on superbru.com):**

| Pool | Players | Priority | Status |
|------|---------|----------|--------|
| URC Predictor | 40,414 | 🔴 First — biggest SA rugby pool | ✅ Created — code: falxcame |
| PSL Predictor | Active | 🟡 Second — SA football core audience | ⏳ Not yet created |
| Super Rugby Pacific | 25,648 | 🟢 Optional | ⏳ Not yet created |
| Varsity Cup | 8,871 | 🟢 SA-only, good local angle | ⏳ Not yet created |

**Banter board:** Live post-match commentary, fixture previews, daily engagement. COO generates ready-to-post banter board content daily via `daily-superbru-scan` task (09:15 SAST).

**Commercial path:** Contact sales@superbru.com for partnership discussions post-launch.

**COO daily scan:** Monitor active pools, note result deadlines, generate banter board content, surface new pool opportunities.

### Telegram Content Laws (UPDATED 16 Apr 2026)

> **Full posting cadence, timing, weekly calendar → [`ops/MARKETING-CORE.md`](MARKETING-CORE.md)**

**Two Telegram surfaces with distinct roles:**

**@MzansiEdgeAlerts (Alerts):** Primary broadcast. Diamond/Gold Edge Pick cards + daily P&L recap. 3/day, hard cap at 4. Quality gate: only Diamond and Gold tier auto-publish. Content mix: 70% Edge cards, 15% P&L, 10% polls/reactions, 5% market commentary. NRGP footer mandatory on every post. Never post after 22:00 SAST.

**@MzansiEdge (Community):** Discussion, not broadcast. 4 seeded posts/day (08:00, 12:00, 15:00, 20:00). Polls, match threads, discussion prompts, quizzes. NEVER repost Edge cards without discussion framing. Admin follow-up within 30-60 min on every seeded post. `18+ · Play Responsibly` only (closed community).

**Visual enrichment:** 80% of Alerts posts include an NB Pro comic-illustrated image. 20% are text-only (breaking news, live commentary). Emojis: 2-4 per post, functional not decorative.

### WhatsApp Channel Laws (UPDATED 16 Apr 2026)

> **Full posting cadence → [`ops/MARKETING-CORE.md`](MARKETING-CORE.md) §3**

**Channel:** https://whatsapp.com/channel/0029VbCS3iR1dAvybnSrVD1D
**WAHA API:** `http://37.27.179.53:3000`, API key: `6375ca0544b848f7b164768d4fab85bb`, session: `default`, chatId: `120363426000312677@newsletter`

**Content strategy: Curated subset of Telegram.** Top 20-30% of picks only. Newspaper front page vs Telegram's live ticker. WhatsApp is muted by default — 8-12% view rate ceiling is structural, not fixable through volume.

**Frequency:** 1-2 posts/day, max 10/week. Never more than 3 in a single day.

**Posting windows:**
- **09:00 SAST** — Daily edge digest (top 1-3 Diamond/Gold picks)
- **19:00 SAST** — Results recap or next-day preview
- **13:00 SAST** (heavy match days only) — Single best-edge Match Day Alert

**Format:** High-contrast card designs (WA compresses aggressively). Captions 2-3 lines max. NRGP disclaimer on every post. Every other post: soft CTA "Get real-time alerts → join our Telegram."

**What NOT to post:** Filler ("no edge found today"), posts after 22:00, Telegram's in-play updates or detailed reasoning, real-time content (WA is a daily digest surface).

**WhatsApp CTA (LOCKED):** `Follow MzansiEdge for daily insights: go.mzansiedge.co.za/join-wa`

**Formatting rules:** No Markdown. Plain text only. Emojis sparingly (max 2 per post).

**Publishing routing:** Python publisher → WAHA API `POST /api/sendText` (http://37.27.179.53:3000) → Notion status updated to Published.

### Image vs Text Decision Rule (LOCKED — 24 March 2026)

**Images are available on all channels but must only be used when they genuinely add value.** Not every post gets an image. An image that doesn't add to the content is visual noise — it dilutes the brand and trains the algorithm to ignore us.

**Use an image when:**
- The post is inherently visual (kit reveal, match day atmosphere, product screenshot, stat comparison)
- The image carries information the copy alone cannot (odds comparison graphic, Edge card visual, B.R.U. content)
- The platform rewards images over text for reach (Instagram always, Facebook usually, LinkedIn occasionally)

**Do NOT use an image when:**
- It's a hot take, opinion, or real-time commentary — text posts perform better for engagement/debate
- The image would be generic or decorative (no value added = don't add it)
- It would slow down a timely post (breaking news, match commentary)
- The post is already strong as text-only copy

**Channel defaults:**
- **TG Alerts:** Image-first. 80% of posts include NB Pro comic-illustrated image. 20% text-only for breaking news/live commentary.
- **TG Community:** Mixed. Polls = text. Match threads = text. Discussion seeds = image when it adds value.
- **WhatsApp Channel:** Image-first. High-contrast Edge Pick card with condensed caption. Card must be legible at WA's compressed quality.
- **Instagram:** Always image or reel. No text-only posts. Carousels for multi-pick match days.
- **TikTok:** Always video. B.R.U character content only. Never Edge Pick card images.
- **LinkedIn:** Text-first. Founder voice posts rarely need images. Use only for product visuals or launch moments.
- **Facebook Groups:** Image + substantive copy paired. Image grabs attention, copy drives discussion. Never image-only.
- **X/Twitter:** SUSPENDED. No new content.

**COO enforces this rule at queue creation time.** If a post is queued with an image, the image must justify itself. If it can't, queue as text-only.

### Image Production Rule (UPDATED — 18 April 2026 · OpenRouter banned)

ALL images generated by COO via **NB2 (`gemini-3.1-flash-image-preview`) through the DIRECT Google Gemini API**. Paul NEVER generates images. No stock images, no Canva, no DALL-E. Every image goes through Paul for approval via Task Hub before publishing.

**LOCKED 18 Apr 2026:** OpenRouter is **BANNED** for image generation — it routed to NB Pro and cost $52/day. OpenRouter is reserved for Sonnet verdict calls only.

**Primary tool:** NB2 via direct Gemini API. See `nb2-image-gen` skill for canonical prompt template + QA checklist; see `.claude/skills/nb2-image-gen/references/gemini-api-call.md` for the call shape.
**API:** Google Gemini direct (`google-genai` SDK v1.73.1+, `from google import genai`), model: `gemini-3.1-flash-image-preview`
**Key:** In `/home/paulsportsza/publisher/.env` and `/home/paulsportsza/bot/.env` (`GEMINI_API_KEY`)
**Post-production:** Logo compositor mandatory (`/home/paulsportsza/publisher/image_compositor.py`). Raw NB2 output NEVER ships without logo overlay.

**Prompt format:** Always start with "Generate an image:" — never use "nano-banana" or any tool-specific prefix.

**Prompt style (LOCKED — 22 March 2026):** Cel-shaded cartoon illustration style. Dramatic cinematic lighting. Warm orange/amber atmosphere. Emotionally resonant scenes. SA cultural context where relevant. NOT flat graphic design, NOT dark backgrounds with text overlays, NOT generic infographic style. Ultra-dramatic — explosions, shockwaves, extreme camera angles, heavy atmospheric particles.

**Mandatory prompt elements:**
1. **Scene/story first** — describe the dramatic visual scene (discovery moment, contrast, tension, action). Rich narrative depth — 200+ words per prompt.
2. **Lighting** — dramatic cinematic lighting, warm orange rim light, amber glow, cyan accents where appropriate. God-rays, harsh floodlights, sparkle particles.
3. **Style** — "cel-shaded cartoon illustration style with bold clean outlines and rich colour saturation" (ALWAYS include this exact phrase)
4. **Brand colours** — Carbon Black #0A0A0A backgrounds, orange gradient #F8C830→#E8571F for accents/light sources. Specify exact hex codes, never vague colour descriptions.
5. **Text overlay** — bold text in Outfit Bold font, punch word in orange gradient fill (#F8C830→#E8571F), rest in Signal White (#F5F5F5)
6. **NO border** — "NO border around the image" (ALWAYS include this. Never add borders.)
7. **Dimensions** — specify size (1080×1080 square, 1200×630 blog, 1080×1920 story)
8. **"8K"** at the end for quality
9. **No logo** on social images

**Reference prompts (approved style — 21 March 2026):**

```
Generate an image: Dramatic treasure discovery moment, a glowing diamond crystal
emerging from cracked dark earth, brilliant cyan blue and amber orange light
radiating outward from the diamond into the darkness, sparkle particles and light
flares erupting upward, the ground around it is dark carbon black cracked rock,
the diamond is the sole source of light in the scene, feels like discovering
something rare and valuable buried underground, cinematic dramatic lighting,
cel-shaded cartoon illustration style, bold text at bottom reading 'Your Edge Is
Waiting.' in Outfit Bold font, 'Your' in white and 'Edge Is Waiting.' in orange
gradient fill from #F8C830 to #E8571F, 1080x1080 square, 8K
```

```
Generate an image: Dramatic close-up of two hands side by side on a dark surface,
left hand crushing a losing betting slip in frustration, right hand smoothly
holding a glowing golden betting slip that radiates warm amber light, the contrast
between failure and smart betting, dark moody atmospheric lighting with warm orange
rim light from the right, shallow depth of field, dust particles in the light beam,
cel-shaded cartoon illustration style, bold text overlay reading 'Wrong pick? Or
wrong price?' in Outfit Bold font, 'Wrong pick? Or' in white and 'wrong price?' in
orange gradient fill from #F8C830 to #E8571F, 1080x1080 square, 8K
```

```
Generate an image: Dark Carbon Black (#0A0A0A) background. Dynamic cricket batsman
mid-swing in silhouette, ball trailing orange gradient (#F8C830→#E8571F) light streak.
Stadium floodlights as subtle starburst in background. Bold headline in Signal White
(#F5F5F5) Outfit Bold: "SA20" in orange gradient fill, "DECODED" in white below.
Faint data grid overlay with Geist Mono numbers at 10% opacity. Thin 2-3px orange
gradient border. Dimensions: 1200×630. No logos.
```

**Prompt construction checklist (before every generation):**
1. ✅ Read Copywriting DNA for headline/hook
2. ✅ Scene is emotionally resonant, not generic — 200+ word rich narrative
3. ✅ "cel-shaded cartoon illustration style with bold clean outlines and rich colour saturation" included
4. ✅ Brand colours specified with exact hex codes (not described vaguely)
5. ✅ Punch word in orange gradient fill (#F8C830→#E8571F), rest in Signal White (#F5F5F5)
6. ✅ "NO border around the image" included (NEVER add borders)
7. ✅ Correct dimensions for target platform
8. ✅ "8K" quality tag at end
9. ✅ Using NB2 model (`gemini-3.1-flash-image-preview`) via DIRECT Google Gemini API — NOT OpenRouter

### Paid Ad Creative & Landing Page Compliance (LOCKED — 16 April 2026)

> Full paid acquisition strategy in `ops/MARKETING-CORE.md` Section 10. This section covers content compliance ONLY.

**Two-zone language isolation** — the legal gate holding the entire paid campaign together:

**Zone 1: Meta ad surfaces + landing page + WA auto-replies + WA templates**
- **Allowed:** match analytics, match intelligence, form guide, performance data, weekly insights, fixture analysis, free match previews, EPL / PSL / rugby / cricket
- **Forbidden:** bet, betting, tips, picks, odds, bookmaker, wager, punt, prediction (borderline — avoid), Betway, Hollywoodbets, any bookmaker brand, "free bet," "guaranteed win," "money-back"
- **Tagline:** "Predict. Better." or "Analyze. Better." — NEVER "Bet. Better." on Meta surfaces
- **Business category:** "Sports Analytics" — never "Gambling"

**Zone 2: Telegram (bot + channel + group)**
- Full product language unrestricted. "Bet. Better." lives here.

**If Meta rejects creative:** Revise immediately. NEVER appeal — appeals flag the account for manual review. If 2+ creatives rejected in 48h, escalate to strategy-level review and consider pivot to pure "match preview newsletter" framing.

**Landing page compliance:** mzansiedge.co.za/analytics (or equivalent). Zero gambling-adjacent terms. Fires PostHog page_visit + captures fbclid for attribution. Single CTA: "Get Free Match Previews on Telegram."

**WA template compliance:** All templates submitted under Utility or Marketing category. Every template includes POPIA opt-out instruction ("reply STOP to unsubscribe"). Zero gambling language. Submit with 48h buffer for rejection iteration.

### Publishing Flow (UPDATED — 4 April 2026)

**Paul NEVER manually posts to social platforms.** The flow is:
1. **Paul approves content** (checkbox, chat, or explicit "approved") → **COO creates Marketing Ops Queue item immediately in the same response** with ALL required fields (see Queue-First Publishing Law below) → status set to "Approved". No delay. No "next sweep." (Standing Order #17)
2. **Python publisher picks it up at next cron run** — cron fires every 3 hours (`0 */3 * * *`), reads all Approved items where Scheduled Time ≤ now, publishes, updates Notion to Published. No manual webhook firing needed. **⚠️ Until PUBLISHER-SETUP-01 is complete, publisher cannot publish — credentials not in server .env yet.**
3. Python publisher posts to target platform (X, FB, IG, LinkedIn, Telegram, WhatsApp) → updates Notion status to "Published" + sets Published URL.

**If publisher is broken or PUBLISHER-SETUP-01 still pending:** Text-only Telegram/X can be done via direct Bot/API calls. FB/IG/LinkedIn require credentials — cannot publish without them.

**⚠️ CRITICAL: Two separate failure modes exist.** (a) Queue item never created after approval — content rots in Task Hub/chat. Fixed by Standing Order #17: queue item is created the moment approval lands. (b) Publisher cron fails or credentials missing — item sits in "Approved" forever. Fixed by completing PUBLISHER-SETUP-01 + monitoring cron runs.

**How to trigger publisher manually (via server):**
```
ssh paulsportsza@37.27.179.53
cd /home/paulsportsza/publisher && python publisher.py
```

**Idempotency:** Publisher checks Notion status before posting. If already "Published", skips. Safe to re-run.

**Paul's manual-only tasks:**
- LinkedIn connection messages (must come from Paul's profile)
- FB group comments (must come from Paul's profile)
- Quora answers (must come from Paul's profile)
- Approving content in Notion (quality gate)

**COO-generated (Paul approves):**
- ALL NB2 images (blogs, social, any visual) — COO generates via `generate-image.py`, presents to Paul via Task Hub for approval

**Everything else publishes via Python publisher.** Never ask Paul to manually post to X, Facebook page, Instagram, or Telegram.

### Fact-Check System (LOCKED — 27 March 2026)

**All content with specific factual claims must pass 3 verification gates before publishing.**

This system prevents wrong match times, outdated standings, incorrect stats, and stale tournament references from reaching the public. Built because the cost of public factual errors — to trust, authority, and brand — is too high for any single failure to be acceptable.

#### 3-Layer Architecture

| Layer | Where | When | What |
|-------|-------|------|------|
| **L1** | In every content-generation task (Standing Order #20) | At copy creation | WebSearch to verify all specific claims before finalising copy or creating queue item |
| **L2** | `fact-check-pre-publish` scheduled task | 07:30 + 15:30 SAST daily | Scans Approved queue items due in 24h, verifies claims, stamps Compliance Notes, blocks wrong items |
| **L3** | Python publisher (cron `0 */3 * * *`) | Every 3h | Before publishing: checks Compliance Notes for ✅ stamp; runs inline check if missing; hard blocks if ❌ |

#### Verifiable Claim Types (L1 triggers a search on any of these)
- Match kickoff times, dates ("kicks off at 19:30 tonight")
- Current league standings / table positions ("sitting 2nd in the URC")
- Player stats or form figures ("4 goals in 4 games")
- Tournament status — running, upcoming, concluded ("ahead of the SA20 final")
- Current odds or prices from any bookmaker
- Match results or scores
- "Tonight / tomorrow / this weekend" references tied to a specific event

#### Compliance Notes Stamps (set by L2/L3)
- `✅ Fact-checked [HH:MM SAST]` — all claims verified, safe to publish
- `✅ No verifiable claims — opinion/brand post [HH:MM SAST]` — pure opinion, no claims to check
- `✅ Fact-checked + auto-corrected [HH:MM SAST]: [brief note]` — claim was wrong, COO fixed it autonomously, still Approved
- `⚠️ Unverifiable [HH:MM SAST]: [note]` — could not confirm, passed with hedged language

#### Rules
- **Paul never sees fact-check failures.** COO fixes wrong claims autonomously — rewrites affected sentences, re-verifies, updates Notion, proceeds. No Paul input needed.
- L1 is fix-at-source. L2/L3 are backstops. Fix at creation, not after.
- ⚠️ Unverifiable alone does NOT block — pass with hedged language ("reportedly", "expected to").
- ❌ Wrong claim → auto-correct copy, re-verify, stamp "✅ Fact-checked + auto-corrected", log to EdgeOps silently. Item stays Approved.
- Unfixable premise (e.g. match cancelled, entire post has no valid angle) → Archive item, log to EdgeOps silently. Paul does not act.
- EdgeOps corrections log is informational only — corrections are already made.
- NEVER send fact-check alerts to @MzansiEdgeAlerts — EdgeOps only.
- Pure opinion/brand/conceptual posts with no specific claims are exempt from search verification.
- FB group posts, Quora answers, and Task Hub content for Paul must also pass L1 — they're public even if not automated.

### Image-First Law for Facebook and Instagram (LOCKED — 2 April 2026)

**No Facebook or Instagram queue item may be created or moved to "Awaiting Approval" without an Asset Link already set.** This applies to ALL FB page posts and IG posts without exception. The image must be generated (NB Pro via gen_batch.py), uploaded to WordPress, URL verified (HTTP 200), and written to the Asset Link field before the item is surfaced to Paul. An image-less FB or IG approval item is a process failure — the COO catches it before Paul ever sees it. There is no "generate image later" step. Image generation is part of content creation, not a post-creation task.

### Queue-First Publishing Law (LOCKED — 20 March 2026)

**No content is "Approved" until it exists as a Marketing Ops Queue item in Notion with all required publisher fields.**

Approval does NOT happen in TASKS.md, chat, or the Task Hub. It happens when the COO creates a page in the Marketing Ops Queue (`collection://58123052-0e48-466a-be63-5308e793e672`) with ALL of the following fields populated:

| Required Field | Value |
|----------------|-------|
| Title | Descriptive title |
| Channel | X / Facebook / Instagram / LinkedIn / TikTok / **Telegram Image** (NEVER "Telegram" — no text-only WF1 path exists) |
| Final Copy | Complete post text, ready to publish |
| Status | Approved |
| Automation Route | Python publisher |
| Scheduled Time | Target publish datetime (SAST) |
| Bitly Link | Channel-specific Bitly link (Act 2+ only — Act 1 posts exempt) |
| Publisher | Python publisher at /home/paulsportsza/publisher/ — cron `0 */3 * * *` |
| Compliance Pass? | Yes |
| Ready for Automation? | Yes |
| Campaign / Theme | Current phase name |

**If the queue item doesn't exist, the content is not approved. Full stop.**

**COO sweep enforcement:**
- **Planning sweep (08:00):** Verify today's items exist in Marketing Ops Queue with all fields. Python publisher cron (every 3h) handles publishing automatically — no manual webhook firing needed unless cron is broken or PUBLISHER-SETUP-01 is still pending.
- **Publish Prep sweep (16:00):** For every item scheduled TOMORROW → verify Marketing Ops Queue page exists with all fields.
- **Post-publish check:** Verify each item's status changed to "Published" and has a Published URL. If status is still "Approved" after 3h, SSH to server and run `python publisher.py` manually, or check cron logs.
- **TASKS.md language rule:** Never write "POST [content]" in Paul's actions for platform posts. Write "VERIFY [content] queued in Marketing Ops" or create the queue item directly. TASKS.md is Paul's action list, not the publish pipeline.

**The two-step publishing contract (no exceptions):**
1. **Create** the Marketing Ops Queue item with all fields → **immediately on approval** (Standing Order #17). Item is "Approved."
2. **Python publisher runs** → **at next cron tick (every 3h)**, picks up all Approved items where Scheduled Time ≤ now. No manual intervention needed once PUBLISHER-SETUP-01 is complete.
If either step is skipped, nothing publishes.

**Root cause this law prevents:** (a) Content approved in one location (Task Hub, TASKS.md, chat) while the publisher reads from another (Marketing Ops Queue) — fixed by SO #17: queue item created at moment of approval. (b) Queue item created but publisher credentials missing — fixed by completing PUBLISHER-SETUP-01 before expecting live publishes. (c) Publisher runs but Scheduled Time is in the future — publisher skips items where Scheduled Time > now.

### Card Format Law (LOCKED — 5 April 2026)

**⚠️ PRODUCT PHILOSOPHY PIVOT — this overrides all prior narrative format assumptions.**

MzansiEdge sells betting edges that work — NOT sports news and journalism. The long-form narrative approach is replaced by structured card format. Every agent producing bot content must comply.

**Format (non-negotiable):**
- **1024 char caption limit** on photo messages (Telegram hard limit — enforces good design)
- **2-3 line expandable analysis** in `<blockquote expandable>` — accurate, punchy, from verified data only
- **Structured data fields per card:** matchup (bold), odds + bookmaker (monospace), confidence + EV, kickoff time + venue/broadcast
- **One concept per message.** Never bundle unrelated data.
- **One primary CTA per message.** Max 3 buttons.
- **Image cards are the hero.** Pillow-generated 1080×1080 branded cards convey hierarchy that text cannot.

**Accuracy rule (10/10 non-negotiable):**
- Haiku composes the 2-3 line analysis from ONLY our verified DB data (odds_snapshots, standings, lineups, mma_fighters, news_articles, match_results, team_ratings)
- NO LLM general knowledge. Models are trained on old data — accuracy cannot be risked.
- If we don't have data for a claim, we don't make the claim. Honest gaps > hallucinated context.

**Coverage rule:**
- QA measures the FULL product — My Matches + Hot Tips, not just edges.
- Dashboard 17.1% w84 coverage is the real product metric. Edge-only (63.3%) is a subset.
- Target: 90%+ of ALL upcoming matches have structured cards.

**Gold standard:** The UX research doc ("Redesigning MzansiEdge for mobile-first clarity") is the definitive reference for message architecture, notification flow, and information hierarchy.

**Example target format (single pick detail view):**
```
🥇 GOLD EDGE — PSL

Chiefs vs Pirates
📍 Chiefs ML @ 2.40 (Betway)
⭐ Confidence: High | EV: +4.2%
⏰ 19:30 SAST | SuperSport PSL

▸ Analysis (tap to expand)
"Chiefs unbeaten in 6 home matches. Pirates missing
Msimango at CB. SA bookmakers at 2.40+ vs sharp
market at 2.10 — significant value gap."

[← Back] [📊 Stats]
```

### Notification Content Laws (LOCKED — 4 March 2026)

- No win guarantees. Use "edge," "value," "expected value."
- Show losses with same prominence as wins. Include season accuracy.
- 3+ consecutive misses → suppress upgrade CTAs for 48 hours.
- Quiet confidence tone. Let numbers speak. One emoji per section max.
- Responsible gambling footer on monthly reports, trial messages, re-engagement nudges.
- Transparency in losses: "The market was right on this one" — never hide a miss.

### Image Approval Rule (LOCKED — 5 March 2026)

ALL visual assets must go through Paul for approval before posting. Text-only posts can proceed with content approval only.
