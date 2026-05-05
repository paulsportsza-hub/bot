# NB2-ADDENDUM — Crowd Authority Table

*Supplements the NB2 plugin skill (nb2-image-gen/SKILL.md). Where this doc and the plugin conflict, this doc wins — it reflects Paul's locked decisions post-launch.*

---

## HARD RULE: CROWD ACCURACY (LOCKED — Paul, May 2026)

**SA crowd imagery (SA flags, vuvuzelas, SA-coloured scarves) is NEVER the default.**
The crowd in every NB2 prompt must match the actual venue and competition. This is a factual accuracy requirement — a crowd at the Emirates waving SA flags is wrong and undermines brand credibility.

### CROWD AUTHORITY TABLE

| Competition | Venue | Crowd spec |
|---|---|---|
| PSL (Chiefs, Pirates, Sundowns, AmaZulu) | SA stadiums | SA flags, vuvuzelas, team-coloured scarves, Soweto energy |
| Bafana Bafana | SA stadiums | SA flags, vuvuzelas, yellow/green crowd |
| URC — SA teams (Stormers, Bulls, Lions, Sharks) | SA home venues | SA flags, team scarves in team colours |
| URC — SA teams **away** | European venues | Home team crowd only. No SA flags. |
| Super Rugby — SA teams at home | SA venues | SA flags, team scarves |
| Springboks (any venue) | Any | SA flags and green/gold always appropriate — SA team |
| Proteas (any venue) | Any | SA flags and green/gold always appropriate — SA team |
| Currie Cup | SA stadiums | SA flags, provincial team colours |
| Rugby Championship — SA legs | SA venues | SA flags, Springbok green/gold |
| Rugby Championship — away legs | Argentina/Australia/NZ | Host nation crowd. No SA flags. |
| EPL (Arsenal, Man United, Liverpool etc.) | English grounds | Home team colours only. Arsenal = red/white. Man United = red/black. NO SA flags. |
| UCL (non-SA venues) | European stadiums | Home team colours. Appropriate European atmosphere. NO SA flags. |
| Six Nations (non-SA matches) | European host cities | Host nation crowd. NO SA flags. |
| IPL (Indian cities) | Indian stadiums | Indian crowd. Colourful Indian atmosphere. Home team colours. NO SA flags. |
| Boxing / MMA (SA venues) | SA arenas | SA flags in stands acceptable |
| Boxing / MMA (international) | International arenas | Shadowed crowd, no SA flags unless explicitly SA venue |

### How to apply in a prompt

Replace the generic CROWD line with a specific instruction derived from the table above.

**Correct — EPL:**
```
CROWD: Arsenal fans in red and white scarves, typical packed English Premier League stadium atmosphere, passionate home crowd.
```

**Correct — IPL:**
```
CROWD: Indian cricket fans in team colours, packed stadium atmosphere, colourful and energetic Indian crowd.
```

**Correct — Stormers home URC:**
```
CROWD: South African rugby fans waving SA flags and Stormers blue scarves, passionate DHL Stadium home crowd.
```

**Wrong (never write this for an EPL match):**
```
CROWD: South African fans waving SA flags ← BANNED for non-SA venues
```

---

## QA CHECKPOINT

Before passing any NB2 prompt to the API, verify:
- Is this a SA-venue or SA-team match? → SA crowd language permitted
- Is this an overseas competition at a non-SA venue? → Non-SA crowd only
- Does the CROWD line match the competition in the CROWD AUTHORITY TABLE above?

---

## Other Amendments

| Date | Rule | Detail |
|---|---|---|
| May 2026 | Crowd accuracy | SA flags/imagery only at SA-hosted or SA-team events. See table above. |
