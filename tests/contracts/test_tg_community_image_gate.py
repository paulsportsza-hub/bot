"""BUILD-CONTRACT-TESTS-01 — Test 10: TG Community Image Gate

TG-COMMUNITY-IMAGE-LAW (BUILD-NEWS-IMAGE-TG-COMMUNITY-01 — LOCKED 21 Apr 2026):
  (a) When generate_tg_community_image() fails (raises RuntimeError or any Exception),
      notion_client.set_asset_link() must NOT be called — the MOQ row is left unchanged.
      The generator uses `continue` to skip the asset-link update on failure.
  (b) WA Channel rows are TEXT-ONLY: create_wa_channel_draft() must never set
      asset_link in the Notion payload.

Static analysis — no live Notion or image API calls.
"""
import os
import re


_GENERATOR_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "publisher", "autogen", "tg_community_image_generator.py"
))
_NOTION_CLIENT_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "publisher", "notion_client.py"
))


def _read_source(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _find_gen_call_pos(src: str) -> int:
    """Return the string offset of the asset_url = generate_tg_community_image( call.

    The docstring on line 8 also contains 'generate_tg_community_image()' so we
    search for the specific assignment pattern to avoid false positives.
    """
    pos = src.find("asset_url = generate_tg_community_image(")
    assert pos >= 0, (
        "Pattern 'asset_url = generate_tg_community_image(' not found in "
        "tg_community_image_generator.py — the generator must assign the image URL "
        "to asset_url before passing it to set_asset_link."
    )
    return pos


# ── (a) Image generation failure must NOT call set_asset_link ─────────────────

def test_generator_uses_continue_on_image_failure():
    """When generate_tg_community_image() raises, `continue` skips set_asset_link.

    The structural pattern in main() must be:
      try:
          asset_url = generate_tg_community_image(...)
      except Exception ...:
          ...
          continue   ← must appear before any set_asset_link call
      ...
      notion_client.set_asset_link(...)  ← only reached on success

    This ensures the MOQ row is never updated when image generation fails.
    """
    src = _read_source(_GENERATOR_PATH)

    # Sanity: set_asset_link must exist (success path)
    assert "set_asset_link" in src, (
        "set_asset_link not found in tg_community_image_generator.py — "
        "generator must call it on success"
    )

    gen_call_pos = _find_gen_call_pos(src)

    # Find the next `except` clause after the actual call
    except_pos = src.find("except Exception", gen_call_pos)
    assert except_pos >= 0, (
        "No `except Exception` found after the generate_tg_community_image() call"
    )

    # The except block ends at the next `try:` at the same indentation level
    # (the set_asset_link try block) — 8 spaces indent inside the for loop.
    next_try_pos = src.find("        try:", except_pos + 1)
    if next_try_pos < 0:
        next_try_pos = len(src)

    except_block = src[except_pos:next_try_pos]
    assert "continue" in except_block, (
        "TG-COMMUNITY-IMAGE-LAW VIOLATION: the `except Exception` block that catches "
        "generate_tg_community_image() failures must use `continue` to skip the "
        "set_asset_link call. Without `continue`, a failed image generation would still "
        "attempt to write an empty/None asset_link to Notion."
    )


def test_set_asset_link_not_inside_image_generation_except():
    """set_asset_link must NOT appear inside the except block for image generation.

    If set_asset_link were inside the except block, it would be called on failure
    (e.g. with asset_url=None or an empty string), corrupting the Notion row.
    """
    src = _read_source(_GENERATOR_PATH)

    gen_call_pos = _find_gen_call_pos(src)

    except_pos = src.find("except Exception", gen_call_pos)
    assert except_pos >= 0

    next_try_pos = src.find("        try:", except_pos + 1)
    if next_try_pos < 0:
        next_try_pos = len(src)

    except_block = src[except_pos:next_try_pos]
    assert "set_asset_link" not in except_block, (
        "TG-COMMUNITY-IMAGE-LAW VIOLATION: set_asset_link must not appear inside "
        "the image generation except block — it must only be called on success "
        "(after a clean asset_url is obtained)."
    )


def test_image_failure_path_calls_continue_not_set_asset_link():
    """Structural: success path has set_asset_link AFTER the image-gen except block.

    Confirms: except(image fail) → continue; then on success → set_asset_link.
    """
    src = _read_source(_GENERATOR_PATH)

    gen_call_pos = _find_gen_call_pos(src)
    except_pos = src.find("except Exception", gen_call_pos)
    assert except_pos >= 0

    next_try_pos = src.find("        try:", except_pos + 1)
    if next_try_pos < 0:
        next_try_pos = len(src)

    after_except = src[next_try_pos:]
    assert "set_asset_link" in after_except, (
        "set_asset_link must appear in the try block AFTER the image generation "
        "except — confirming it is only reached on success"
    )


# ── (b) WA Channel rows include asset_link only when supplied ─────────────────

def test_create_wa_channel_draft_asset_link_is_conditional():
    """create_wa_channel_draft() only sets Asset Link when asset_url is supplied.

    Later WA Channel NB2-image support allows an optional image, but the helper
    must not write an empty Asset Link property for text-only rows.
    """
    src = _read_source(_NOTION_CLIENT_PATH)

    fn_match = re.search(
        r"^def create_wa_channel_draft\s*\(.*?\n(.*?)(?=\n^def |\Z)",
        src,
        re.DOTALL | re.MULTILINE,
    )
    assert fn_match, "create_wa_channel_draft not found in notion_client.py"

    body = fn_match.group(0)

    assert "asset_url: str = \"\"" in body
    assert "if asset_url:" in body
    assert 'props["Asset Link"] = {"url": asset_url}' in body


def test_wa_channel_draft_missing_from_image_generator_loop():
    """The image generator explicitly targets TG Community rows, not WA Channel rows."""
    src = _read_source(_GENERATOR_PATH)
    assert "tg_community" in src.lower(), (
        "Image generator must explicitly query tg_community rows — "
        "not a generic query that could include WA Channel rows"
    )


def test_generate_tg_community_image_function_present():
    """generate_tg_community_image import and call must be present in the generator."""
    src = _read_source(_GENERATOR_PATH)
    assert "generate_tg_community_image" in src, (
        "generate_tg_community_image not found in tg_community_image_generator.py"
    )


def test_notion_client_set_asset_link_exists():
    """notion_client.set_asset_link() must be defined — it is the success path."""
    src = _read_source(_NOTION_CLIENT_PATH)
    assert re.search(r"^def set_asset_link\s*\(", src, re.MULTILINE), (
        "set_asset_link not defined in notion_client.py"
    )
