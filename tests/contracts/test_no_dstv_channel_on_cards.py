"""
Contract: BUILD-KO-SUPERSPORT-PRIMARY-01 — SuperSport is the primary authoritative
source for kickoff times AND broadcast channels across ALL sports. SUPERSEDES
FIX-DSTV-CHANNEL-PERM-01 which permanently removed channel display.

Layers:
  Layer 1 — Legacy broadcast-line stub functions stay inert (pre-existing DStv
            text builders must remain empty; channel now flows via dedicated
            _get_supersport_channel() helper + tip["channel"] pass-through).
  Layer 2 — card_data builders MUST pass tip["channel"] through (no hardcoded "").
  Layer 3 — Templates MUST render the channel as a meta-item when present.
  Layer 4 — card_pipeline.render_card_html() keeps its broadcast_channel="" guard
            (unrelated to the new text-based channel line — no reintroduction of
            the old DStv-number hardcoded pipeline).
"""

import importlib
import pathlib
import re
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Layer 1 — Source functions return empty broadcast
# ---------------------------------------------------------------------------

class TestBroadcastSourceFunctions(unittest.TestCase):
    """_get_broadcast_details() and _get_broadcast_line() must return '' broadcast."""

    def _import_bot(self):
        """Import bot module with all heavy deps stubbed."""
        stubs = [
            "telegram", "telegram.ext", "telegram.error",
            "anthropic", "sentry_sdk", "posthog",
            "scripts.odds_client", "scripts.picks_engine", "scripts.sports_data",
            "scripts.live_scores", "scripts.telegraph_guides",
            "services.user_service", "services.schedule_service",
            "services.picks_service", "services.analytics",
            "services.edge_rating", "services.affiliate_service",
            "services.odds_service", "services.templates",
            "renderers.edge_renderer", "renderers.telegram_renderer",
            "scrapers.broadcast_scraper", "scrapers.broadcast_matcher",
            "scrapers.odds_normaliser",
        ]
        for name in stubs:
            parts = name.split(".")
            for i in range(1, len(parts) + 1):
                mod_name = ".".join(parts[:i])
                if mod_name not in sys.modules:
                    sys.modules[mod_name] = types.ModuleType(mod_name)
        if "bot" in sys.modules:
            del sys.modules["bot"]
        return None  # bot import is heavy; use grep-based checks below

    def test_format_fixture_broadcast_returns_empty_string(self):
        """_format_fixture_broadcast() must always return ''."""
        # Grep the source so we don't need a full bot import
        bot_path = pathlib.Path(__file__).parent.parent.parent / "bot.py"
        src = bot_path.read_text()

        # The function must exist and must return ""
        self.assertIn("def _format_fixture_broadcast", src,
                      "_format_fixture_broadcast() must exist in bot.py")
        # After the function definition, the first non-comment, non-docstring return must be ""
        fn_match = re.search(
            r'def _format_fixture_broadcast\(.*?\).*?:\n(.*?)(?=\ndef |\Z)',
            src, re.DOTALL
        )
        self.assertIsNotNone(fn_match, "_format_fixture_broadcast body not found")
        body = fn_match.group(1)
        self.assertIn('return ""', body,
                      "_format_fixture_broadcast must return empty string")

    def test_get_broadcast_line_returns_empty_string(self):
        """_get_broadcast_line() must always return ''."""
        bot_path = pathlib.Path(__file__).parent.parent.parent / "bot.py"
        src = bot_path.read_text()

        self.assertIn("def _get_broadcast_line", src,
                      "_get_broadcast_line() must exist in bot.py")
        fn_match = re.search(
            r'def _get_broadcast_line\(.*?\).*?:\n(.*?)(?=\ndef |\Z)',
            src, re.DOTALL
        )
        self.assertIsNotNone(fn_match)
        body = fn_match.group(1)
        self.assertIn('return ""', body,
                      "_get_broadcast_line must return empty string")

    def test_get_broadcast_details_does_not_set_broadcast_field(self):
        """_get_broadcast_details() must NOT assign a non-empty broadcast value."""
        bot_path = pathlib.Path(__file__).parent.parent.parent / "bot.py"
        src = bot_path.read_text()

        fn_match = re.search(
            r'def _get_broadcast_details\(.*?\).*?:\n(.*?)(?=\ndef |\Z)',
            src, re.DOTALL
        )
        self.assertIsNotNone(fn_match, "_get_broadcast_details() not found in bot.py")
        body = fn_match.group(1)

        # Must NOT contain the old assignment patterns that built channel strings
        self.assertNotIn('"DStv"', body,
                         "_get_broadcast_details must not build DStv strings")
        self.assertNotIn("channel_short", body,
                         "_get_broadcast_details must not reference channel_short")
        self.assertNotIn("dstv_number", body,
                         "_get_broadcast_details must not reference dstv_number")

    def test_build_event_header_broadcast_line_is_empty(self):
        """_build_event_header() must always return broadcast_line=''."""
        bot_path = pathlib.Path(__file__).parent.parent.parent / "bot.py"
        src = bot_path.read_text()

        fn_match = re.search(
            r'def _build_event_header\(.*?\).*?:\n(.*?)(?=\ndef |\Z)',
            src, re.DOTALL
        )
        if fn_match is None:
            self.skipTest("_build_event_header not found — check wave scope")
        body = fn_match.group(1)
        # broadcast_line must be hardcoded empty
        self.assertIn('"broadcast_line": ""', body,
                      "_build_event_header must return broadcast_line as empty string")


# ---------------------------------------------------------------------------
# Layer 2 — card_data builders produce empty channel fields
# ---------------------------------------------------------------------------

class TestCardDataBuilders(unittest.TestCase):
    """card_data.py builder functions must produce empty channel fields."""

    def _load_card_data(self):
        import importlib
        cd_path = pathlib.Path(__file__).parent.parent.parent / "card_data.py"
        spec = importlib.util.spec_from_file_location("card_data", cd_path)
        mod = importlib.util.module_from_spec(spec)
        # Provide minimal stubs for card_data imports
        for dep in ("PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont",
                    "jinja2", "cairosvg"):
            if dep not in sys.modules:
                sys.modules[dep] = types.ModuleType(dep)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            pass  # best-effort; use grep if import fails
        return mod

    def test_channel_fields_stub_returns_empty(self):
        """_channel_fields() must return channel_number='', channel_is_ss=False, ss_logo_b64=''."""
        src_path = pathlib.Path(__file__).parent.parent.parent / "card_data.py"
        src = src_path.read_text()

        fn_match = re.search(
            r'def _channel_fields\(.*?\).*?:\n(.*?)(?=\ndef |\Z)',
            src, re.DOTALL
        )
        self.assertIsNotNone(fn_match, "_channel_fields() must exist in card_data.py")
        body = fn_match.group(1)
        self.assertIn('"channel_number": ""', body,
                      "_channel_fields must return empty channel_number")
        self.assertIn('"channel_is_ss": False', body,
                      "_channel_fields must return channel_is_ss=False")
        self.assertIn('"ss_logo_b64": ""', body,
                      "_channel_fields must return empty ss_logo_b64")

    def _assert_channel_pass_through_in_builder(self, fn_name: str):
        src_path = pathlib.Path(__file__).parent.parent.parent / "card_data.py"
        src = src_path.read_text()
        fn_match = re.search(
            rf'def {re.escape(fn_name)}\(.*?\).*?:\n(.*?)(?=\ndef |\Z)',
            src, re.DOTALL
        )
        self.assertIsNotNone(fn_match, f"{fn_name}() not found in card_data.py")
        body = fn_match.group(1)
        # channel key MUST NOT be hardcoded empty (BUILD-KO-SUPERSPORT-PRIMARY-01
        # supersedes FIX-DSTV-CHANNEL-PERM-01 — SuperSport data must flow through).
        self.assertNotIn(
            '"channel": ""', body,
            f'{fn_name} must not hardcode "channel": "" '
            '(BUILD-KO-SUPERSPORT-PRIMARY-01 requires pass-through)'
        )
        # Must read channel from the source dict (tip/m/match).get("channel").
        self.assertRegex(
            body,
            r'"channel":\s*\w+\.get\("channel"\)',
            f'{fn_name} must pass channel through via .get("channel") '
            '(BUILD-KO-SUPERSPORT-PRIMARY-01)'
        )

    def test_build_match_detail_data_channel_pass_through(self):
        self._assert_channel_pass_through_in_builder("build_match_detail_data")

    def test_build_edge_detail_data_channel_pass_through(self):
        self._assert_channel_pass_through_in_builder("build_edge_detail_data")

    def test_build_my_matches_data_channel_pass_through(self):
        self._assert_channel_pass_through_in_builder("build_my_matches_data")


# ---------------------------------------------------------------------------
# Layer 3 — Templates contain no active channel rendering
# ---------------------------------------------------------------------------

class TestTemplatesChannelRendering(unittest.TestCase):
    """BUILD-KO-SUPERSPORT-PRIMARY-01: match_detail.html MUST render the channel
    as a conditional meta-item. Other templates still must not emit DStv-number
    legacy patterns (channel_number / CSS-class-based channel blocks)."""

    TEMPLATES_DIR = pathlib.Path(__file__).parent.parent.parent / "card_templates"

    # Legacy patterns that must NEVER return (DStv-number-based channel rendering).
    LEGACY_CHANNEL_PATTERNS = [
        r'\{%-?\s*if\s+channel_number\s*-?%\}',    # {% if channel_number %}
        r'\{\{\s*channel_number\s*\}\}',            # {{ channel_number }}
        r'class=".*?channel.*?"',                   # CSS class for channel block
    ]

    def _get_legacy_channel_hits(self, template_path: pathlib.Path) -> list[str]:
        src = template_path.read_text()
        hits = []
        for pat in self.LEGACY_CHANNEL_PATTERNS:
            for m in re.finditer(pat, src):
                line = src[:m.start()].count("\n") + 1
                hits.append(f"line {line}: {m.group()!r}")
        return hits

    def test_match_detail_renders_channel_meta_item(self):
        """match_detail.html MUST render 📺 {{ channel }} gated by {% if channel %}."""
        t = self.TEMPLATES_DIR / "match_detail.html"
        if not t.exists():
            self.skipTest("match_detail.html not found")
        src = t.read_text()
        # Must render channel conditionally as a meta-item
        self.assertRegex(
            src,
            r'\{%-?\s*if\s+channel\s*-?%\}.*?📺\s*\{\{\s*channel\s*\}\}',
            "match_detail.html must render 📺 {{ channel }} inside {% if channel %} "
            "(BUILD-KO-SUPERSPORT-PRIMARY-01)"
        )
        # Must not have legacy DStv-number channel patterns
        legacy = self._get_legacy_channel_hits(t)
        self.assertEqual(
            legacy, [],
            "match_detail.html must not contain legacy DStv-number channel rendering:\n"
            + "\n".join(legacy)
        )

    def test_edge_detail_no_legacy_channel(self):
        t = self.TEMPLATES_DIR / "edge_detail.html"
        if not t.exists():
            self.skipTest("edge_detail.html not found")
        legacy = self._get_legacy_channel_hits(t)
        self.assertEqual(
            legacy, [],
            "edge_detail.html must not contain legacy DStv-number channel rendering:\n"
            + "\n".join(legacy)
        )

    def test_my_matches_no_legacy_channel(self):
        t = self.TEMPLATES_DIR / "my_matches.html"
        if not t.exists():
            self.skipTest("my_matches.html not found")
        legacy = self._get_legacy_channel_hits(t)
        self.assertEqual(
            legacy, [],
            "my_matches.html must not contain legacy DStv-number channel rendering:\n"
            + "\n".join(legacy)
        )

    def test_tier_page_no_legacy_channel(self):
        t = self.TEMPLATES_DIR / "tier_page.html"
        if not t.exists():
            self.skipTest("tier_page.html not found")
        legacy = self._get_legacy_channel_hits(t)
        self.assertEqual(
            legacy, [],
            "tier_page.html must not contain legacy DStv-number channel rendering:\n"
            + "\n".join(legacy)
        )


# ---------------------------------------------------------------------------
# Layer 4 — card_pipeline.render_card_html() produces no channel content
# ---------------------------------------------------------------------------

class TestCardPipelineNoBroadcast(unittest.TestCase):
    """render_card_html() must not include broadcast/channel content."""

    def test_render_card_html_no_broadcast_variable(self):
        """The dead `broadcast = card_data.get("broadcast", "")` line must be gone."""
        src_path = pathlib.Path(__file__).parent.parent.parent / "card_pipeline.py"
        src = src_path.read_text()

        # Find the render_card_html function body
        fn_match = re.search(
            r'def render_card_html\(.*?\).*?:\n(.*?)(?=\ndef |\Z)',
            src, re.DOTALL
        )
        if fn_match is None:
            self.skipTest("render_card_html not found in card_pipeline.py")
        body = fn_match.group(1)

        # Must not have the old unguarded broadcast assignment
        self.assertNotIn(
            'broadcast = card_data.get("broadcast"',
            body,
            "render_card_html must not read broadcast from card_data — "
            "this was removed in FIX-DSTV-CHANNEL-PERM-01"
        )

    def test_card_pipeline_broadcast_always_empty(self):
        """broadcast_channel field must be hardcoded '' in card_pipeline.py."""
        src_path = pathlib.Path(__file__).parent.parent.parent / "card_pipeline.py"
        src = src_path.read_text()
        self.assertIn(
            '"broadcast_channel": ""',
            src,
            'card_pipeline.py must have "broadcast_channel": "" (FIX-DSTV-CHANNEL-PERM-01)'
        )

    def test_message_types_no_broadcast_append(self):
        """message_types.py must not append a broadcast line."""
        src_path = pathlib.Path(__file__).parent.parent.parent / "message_types.py"
        if not src_path.exists():
            self.skipTest("message_types.py not found")
        src = src_path.read_text()
        # The old pattern was: if broadcast: lines.append(broadcast)
        self.assertNotRegex(
            src,
            r'if\s+broadcast\s*:\s*\n?\s*lines\.append\(broadcast\)',
            "message_types.py must not conditionally append broadcast line"
        )

    def test_card_generator_no_broadcast_draw(self):
        """card_generator.py must not draw a broadcast/channel string."""
        src_path = pathlib.Path(__file__).parent.parent.parent / "card_generator.py"
        if not src_path.exists():
            self.skipTest("card_generator.py not found")
        src = src_path.read_text()
        # Old pattern: draw.text(... f"📺 {broadcast}" ...)
        self.assertNotRegex(
            src,
            r'📺.*broadcast',
            "card_generator.py must not draw 📺 broadcast strings"
        )
        self.assertIn(
            "FIX-DSTV-CHANNEL-PERM-01",
            src,
            "card_generator.py must contain FIX-DSTV-CHANNEL-PERM-01 removal comment"
        )


if __name__ == "__main__":
    unittest.main()
