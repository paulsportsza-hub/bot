"""Public import surface for narrative persistence validators."""
from __future__ import annotations

import pytest


def test_public_names_importable():
    from narrative_validator import (
        validate_narrative_for_persistence,
        validate_verdict_for_persistence,
    )

    assert callable(validate_narrative_for_persistence)
    assert callable(validate_verdict_for_persistence)


def test_underscore_names_not_importable():
    with pytest.raises(ImportError):
        from narrative_validator import _validate_narrative_for_persistence  # noqa: F401

    with pytest.raises(ImportError):
        from narrative_validator import _validate_verdict_for_persistence  # noqa: F401
