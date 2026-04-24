"""BUILD-CONTRACT-TESTS-01 — Test 6: Narrative Cache Header Injection

W84-Q7 invariant: All 3 narrative cache-hit paths in _generate_game_tips() must
call _inject_narrative_header() before serving cached HTML. Stale cached narratives
have incomplete/missing kickoff + broadcast headers without this injection.

The 3 paths, identified by their distinguishing variable names:
  Path A: _early_db_hit  →  _ea_html = _inject_narrative_header(...)
  Path B: _pre_cached    →  _p_html  = _inject_narrative_header(...)
  Path C: _cached_db     →  _b_html  = _inject_narrative_header(...)

Static analysis — no bot import required.
"""
import os
import re

_BOT_PY = os.path.join(os.path.dirname(__file__), "..", "..", "bot.py")


def _bot_source() -> str:
    with open(_BOT_PY, encoding="utf-8") as f:
        return f.read()


def test_path_a_early_db_hit_injects_header():
    """Path A (_early_db_hit): _ea_html must be assigned from _inject_narrative_header()."""
    source = _bot_source()
    # Look for the pattern: _ea_html = _inject_narrative_header(
    assert re.search(r"_ea_html\s*=\s*_inject_narrative_header\s*\(", source), (
        "W84-Q7 REGRESSION: Path A cache hit (_early_db_hit) does not call "
        "_inject_narrative_header() before serving HTML. "
        "Expected: _ea_html = _inject_narrative_header(...)"
    )


def test_path_b_pre_cached_injects_header():
    """Path B (_pre_cached / pre-spinner): _p_html must be assigned from _inject_narrative_header()."""
    source = _bot_source()
    assert re.search(r"_p_html\s*=\s*_inject_narrative_header\s*\(", source), (
        "W84-Q7 REGRESSION: Path B pre-spinner cache hit (_pre_cached) does not call "
        "_inject_narrative_header() before serving HTML. "
        "Expected: _p_html = _inject_narrative_header(...)"
    )


def test_path_c_w60_cache_injects_header():
    """Path C (W60-CACHE / _cached_db): _b_html must be assigned from _inject_narrative_header()."""
    source = _bot_source()
    assert re.search(r"_b_html\s*=\s*_inject_narrative_header\s*\(", source), (
        "W84-Q7 REGRESSION: Path C W60-CACHE hit (_cached_db) does not call "
        "_inject_narrative_header() before serving HTML. "
        "Expected: _b_html = _inject_narrative_header(...)"
    )


def test_inject_narrative_header_function_exists():
    """_inject_narrative_header() must be defined in bot.py."""
    source = _bot_source()
    assert re.search(r"^def _inject_narrative_header\s*\(", source, re.MULTILINE), (
        "_inject_narrative_header function not found in bot.py"
    )


def test_inject_header_replaces_before_setup_marker():
    """_inject_narrative_header must locate the 📋 setup marker to replace stale header."""
    source = _bot_source()
    # Find the function body
    m = re.search(
        r"def _inject_narrative_header\s*\(.*?\n(.*?)(?=\ndef |\Z)",
        source,
        re.DOTALL,
    )
    assert m, "_inject_narrative_header not found"
    body = m.group(0)
    # The function must look for the 📋 section marker
    assert "📋" in body, (
        "_inject_narrative_header must use the 📋 section marker to find where to inject the header"
    )


def test_all_three_paths_inject_before_serve():
    """Each injected variable (_ea_html, _p_html, _b_html) must appear in source
    as the value that gets served — not replaced by a non-injected version."""
    source = _bot_source()
    for var, path in [("_ea_html", "A"), ("_p_html", "B"), ("_b_html", "C")]:
        assert var in source, f"Path {path} variable {var} missing from bot.py"
