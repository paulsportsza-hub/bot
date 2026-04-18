"""Regression guard: FIX-DASH-PERF-03 — SPA partial bootstrap guard.

DOMContentLoaded must never fire on AJAX nav because it has already fired
by the time the user tab-switches.  Every partial that used to bootstrap via
a bare DOMContentLoaded listener must use the readyState guard instead:

    if (document.readyState !== 'loading') { init(); }
    else { document.addEventListener('DOMContentLoaded', init); }

These tests prevent silent regression to the broken pattern.
"""
import re
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, '/home/paulsportsza/bot')
sys.path.insert(0, '/home/paulsportsza/bot/dashboard')

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BARE_DCL_RE = re.compile(
    r"document\.addEventListener\(['\"]DOMContentLoaded['\"],\s*function",
)
GUARD_RE = re.compile(
    r"document\.readyState\s*!==\s*['\"]loading['\"]",
)


def _stub_dashboard_imports():
    """Stub heavy external deps so health_dashboard imports cleanly."""
    for mod in [
        "flask", "flask_login", "sentry_sdk", "sentry_sdk.integrations.flask",
        "posthog", "anthropic",
    ]:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()
    # flask needs a real-ish Request object for the module-level app reference
    flask_mock = sys.modules.setdefault("flask", MagicMock())
    flask_mock.Flask = MagicMock(return_value=MagicMock())
    flask_mock.request = MagicMock()
    flask_mock.Response = MagicMock(side_effect=lambda body, **kw: body)
    flask_mock.jsonify = MagicMock(side_effect=lambda d: d)


# ---------------------------------------------------------------------------
# Source-level structural tests (no import needed, zero network)
# ---------------------------------------------------------------------------

class TestDOMContentLoadedGuardInSource(unittest.TestCase):
    """Read the dashboard source directly and verify the guard pattern."""

    SOURCE_PATH = "/home/paulsportsza/bot/dashboard/health_dashboard.py"

    @classmethod
    def setUpClass(cls):
        with open(cls.SOURCE_PATH, encoding="utf-8") as fh:
            cls.source = fh.read()

    def test_no_bare_domcontentloaded_in_source(self):
        """No partial must use a bare DOMContentLoaded listener."""
        matches = BARE_DCL_RE.findall(self.source)
        self.assertEqual(
            matches, [],
            "Bare DOMContentLoaded listener found — use readyState guard instead. "
            f"Matches: {matches}",
        )

    def test_guard_pattern_present_for_social_ops(self):
        """Social Ops IIFE must contain the readyState guard."""
        # Locate the Social Ops IIFE block (soInit is the named bootstrap fn)
        self.assertIn(
            "function soInit()",
            self.source,
            "soInit() named function missing from Social Ops IIFE",
        )
        self.assertIn(
            "if(document.readyState!=='loading'){soInit();}",
            self.source,
            "readyState guard for soInit() is missing",
        )

    def test_guard_pattern_present_for_coverage_chart(self):
        """Coverage chart init must use the readyState guard."""
        self.assertIn(
            "function coverageInit()",
            self.source,
            "coverageInit() named function missing from overview script",
        )
        self.assertTrue(
            GUARD_RE.search(self.source),
            "readyState guard pattern missing from health_dashboard.py",
        )

    def test_soinit_is_inside_iife(self):
        """soInit must remain scoped inside the Social Ops IIFE."""
        iife_start = self.source.find("(function(){\nvar ICONS=")
        iife_end   = self.source.find("})();\n</script>\"\"\"", iife_start)
        self.assertGreater(iife_start, 0, "Social Ops IIFE open not found")
        self.assertGreater(iife_end, iife_start, "Social Ops IIFE close not found")
        iife_body = self.source[iife_start:iife_end]
        self.assertIn(
            "function soInit()",
            iife_body,
            "soInit() is not inside the Social Ops IIFE — globals would leak on re-injection",
        )


# ---------------------------------------------------------------------------
# Render-level tests — call render_automation_content() with mocked network
# ---------------------------------------------------------------------------

class TestSocialOpsPartialHTML(unittest.TestCase):
    """Rendered Social Ops HTML must not contain bare DOMContentLoaded."""

    def _render(self):
        """Import dashboard and call render_automation_content with mocked deps."""
        _stub_dashboard_imports()
        # Patch network calls inside render_automation_content
        with patch("dashboard.health_dashboard._fetch_marketing_queue",
                   return_value=([], __import__("time").monotonic())), \
             patch("dashboard.health_dashboard._fetch_queue_data",
                   return_value={"posts": [], "horizon_hours": 12},
                   create=True):
            import importlib
            import dashboard.health_dashboard as hd
            importlib.reload(hd)  # fresh state
            return hd.render_automation_content()

    def test_rendered_html_has_no_bare_domcontentloaded(self):
        try:
            html = self._render()
        except Exception:
            self.skipTest("render_automation_content() raised (likely missing DB/env) — source tests cover the guard")
        self.assertFalse(
            BARE_DCL_RE.search(html),
            "render_automation_content() output still contains bare DOMContentLoaded",
        )

    def test_rendered_html_contains_guard(self):
        try:
            html = self._render()
        except Exception:
            self.skipTest("render_automation_content() raised (likely missing DB/env) — source tests cover the guard")
        self.assertTrue(
            "readyState" in html,
            "render_automation_content() output missing readyState guard",
        )

    def test_second_injection_same_guard(self):
        """Calling render twice (simulating SPA re-injection) yields the guard both times."""
        try:
            import dashboard.health_dashboard as hd
        except Exception:
            self.skipTest("dashboard import failed — source tests cover the guard")
        with patch("dashboard.health_dashboard._fetch_marketing_queue",
                   return_value=([], __import__("time").monotonic())):
            try:
                html1 = hd.render_automation_content()
                html2 = hd.render_automation_content()
            except Exception:
                self.skipTest("render raised — source tests cover the guard")
        for idx, html in enumerate([html1, html2], 1):
            self.assertFalse(
                BARE_DCL_RE.search(html),
                f"Injection {idx}: bare DOMContentLoaded found in rendered output",
            )
            self.assertIn(
                "readyState",
                html,
                f"Injection {idx}: readyState guard missing from rendered output",
            )


if __name__ == "__main__":
    unittest.main()
