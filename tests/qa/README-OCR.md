# QA Card OCR — SO #38 Workflow Template

Telethon QA sub-agents can now READ the content of a delivered card, not just
confirm it was delivered. This module is the canonical template for every
future BUILD brief that touches a user-facing card.

Built by `BUILD-QA-CARD-OCR-01` (22 Apr 2026). See the brief for scope and
out-of-scope rules.

## What ships

```
tests/qa/
├── vision_ocr.py          # ocr_card() + CardOCR dataclass (Claude Opus 4.7)
├── ocr_prompt.py          # Prompt + ALLOWED_TIER_BADGES
├── card_assertions.py     # 5 content-level assertion helpers
├── ground_truth/          # 3 pinned cards + .expected.json per card
└── test_ocr_ground_truth.py  # pytest -m integration
tests/test_qa_vision_ocr.py   # pytest -q (mocked, no API cost)
```

## Canonical SO #38 sub-agent workflow

```python
# 1. Deliver the card (existing Telethon harness pattern)
screenshot = await telethon_tap_deeplink(bot, match_key)

# 2. OCR it
from tests.qa.vision_ocr import ocr_card
from tests.qa.card_assertions import (
    assert_verdict_in_range,
    assert_not_stub_shape,
    assert_teams_populated,
    assert_tier_badge_present,
)
ocr = ocr_card(screenshot)

# 3. Content assertions
assert_verdict_in_range(ocr)        # verdict body within [100, 260] chars
assert_not_stub_shape(ocr)          # no "— ? at 0.00." stub shape
assert_teams_populated(ocr)         # no blank / HOME / AWAY placeholders
assert_tier_badge_present(ocr)      # one of 💎 🥇 🥈 🥉 rendered
```

Every BUILD brief that renders or changes a card MUST:

1. Tap the card via Telethon (delivery QA — unchanged).
2. Feed the captured screenshot to `ocr_card()`.
3. Run the four core content assertions above.
4. Include the OCR table (match key / verdict first 80 chars / teams /
   tier / pass-fail) in the completion report.

## When to use which assertion helper

| Helper | Fires when |
|---|---|
| `assert_verdict_in_range(ocr, min=100, max=260)` | Verdict body character count out of band. |
| `assert_not_stub_shape(ocr)` | Verdict matches the stub regex `— ? at 0.00.` |
| `assert_teams_populated(ocr)` | Home or away label is blank, or literal `HOME`/`AWAY`. |
| `assert_tier_badge_present(ocr, expected={"🥇", "💎"})` | Tier badge missing, or outside the allowed set. |
| `assert_button_set(ocr, expected_labels=[...])` | Only when the screenshot captures the full Telegram UI below the card image. Card-photo-only captures have `button_count=0`. |

## Running the tests

```bash
# Unit (mocked — no API cost, no network)
bash scripts/qa_safe.sh tests/test_qa_vision_ocr.py

# Ground-truth integration (real API — costs tokens)
bash scripts/qa_safe.sh tests/qa/test_ocr_ground_truth.py -- -m integration
```

Ground-truth test is excluded from `pytest -q` by default (`addopts = -m "not
integration"` in `pytest.ini`). CI stays untouched — local runs only for now.

## Guard rails

- **Model is pinned in one place.** `_MODEL = "claude-opus-4-7"` at the top of
  `vision_ocr.py`. Do not hard-code a model string anywhere else.
- **ANTHROPIC_API_KEY** is required at runtime. Missing key → `RuntimeError`.
  The mocked unit tests stub `anthropic.Anthropic` so they run without one.
- **Opus 4.7 does not accept `temperature`.** Determinism is enforced by the
  JSON-output prompt (see `ocr_prompt.py`), not a sampling flag.
- **Image type is sniffed from magic bytes.** Telegram screenshots sometimes
  land on disk with `.png` extension and JPEG content — the encoder detects
  this and sends the correct media type.
- **Tier badge whitelist is strict.** Any non-{💎 🥇 🥈 🥉} value is rejected
  as a hallucination and stored as `None`.

## Pinning new ground-truth cards

1. Capture via an existing Telethon harness — save the PNG under
   `tests/qa/ground_truth/card_<match_key>.png`.
2. Author `<same-stem>.expected.json` with fields: `verdict_text`, `home_team`,
   `away_team`, `tier_badge`, `match_key`, `source`, `notes`.
3. Run `bash scripts/qa_safe.sh tests/qa/test_ocr_ground_truth.py -- -m integration`.
4. If fuzzy similarity drops below 0.85 across the board, STOP — the OCR
   prompt needs material rework. Escalate to LEAD per the brief's challenge
   rule, don't soften the threshold.

## Don't

- Don't wire OCR into any production code path (publisher, autogen, pregen).
  QA-only.
- Don't add this test to CI. Local-run only until post-launch.
- Don't replace the existing Telethon harnesses — OCR is additive.
- Don't use a non-Claude vision model. Paul's call, see brief.
- Don't pin the model string in a second place. One constant, one import.
