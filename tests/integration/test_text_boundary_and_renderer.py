"""Two C4 fixture additions exercised against the real DLL:

- `fixture.boundary_text_field`: `backend.py`'s chunked `getAccessibleText`
  reads use `CHUNK_SIZE = min(MAX_STRING_SIZE - 1, 32_766) == 1023` UTF-16
  code units. The field's text places a surrogate pair's high surrogate as
  the very last unit of the first chunk and its low surrogate as the very
  first unit of the second - the arrangement most likely to corrupt a naive
  chunk-and-concatenate implementation.
- `fixture.custom_rendered_list`: a `JList` whose cells are rendered by a
  custom `ListCellRenderer`, unlike every other list/table in this fixture.
"""

from __future__ import annotations

import pytest

from play_jab.sync_api import PlayJab

from .conftest import SwingFixture

pytestmark = pytest.mark.integration_jab

_TIMEOUT_MS = 5_000
_BOUNDARY_TEXT = "a" * 1022 + "\U0001f680" + "b" * 978
_HIGH_SURROGATE = "\ud83d"
_LOW_SURROGATE = "\ude80"
# What text_content() actually returns today: each 1023-code-unit chunk is
# decoded to a Python str independently, then the chunks are concatenated as
# already-decoded strings. Two lone surrogates from adjacent chunks do not
# re-combine into one astral codepoint on concatenation the way two adjacent
# UTF-16 code units in the *same* decode would - confirmed empirically
# against the real DLL (chunk 1 ends at code unit 1022 with the high
# surrogate; chunk 2 begins at 1023 with the low surrogate).
_ACTUAL_BOUNDARY_TEXT = "a" * 1022 + _HIGH_SURROGATE + _LOW_SURROGATE + "b" * 978


def test_surrogate_pair_at_the_chunk_boundary_is_split_by_the_real_dll(
    swing_fixture: SwingFixture,
) -> None:
    """Debt marker, not a fixture defect.

    This is the scenario unit-tests-review.md finding B5 asked for a
    real-DLL proof of, and the real answer is a genuine defect: reading text
    whose surrogate pair straddles a `CHUNK_SIZE`-unit boundary returns the
    pair as two lone (unpaired) surrogates instead of one combined
    character, because `backend.py`'s chunked read decodes each chunk's
    buffer to a Python `str` independently before concatenating, rather than
    concatenating the raw UTF-16 code units first and decoding once. Fixing
    this is a `src/play_jab/_native/backend.py` change, out of this
    testing-only plan's scope - this test locks down the exact, currently
    observed (wrong) output so a future library-fixes phase has an
    immediate, precise regression/acceptance test once it is corrected.
    """
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(3)
        try:
            text = window.get_by_name("fixture.boundary_text_field").text_content()
            assert text == _ACTUAL_BOUNDARY_TEXT
            assert text != _BOUNDARY_TEXT
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)


def test_custom_cell_renderer_does_not_break_text_resolution(
    swing_fixture: SwingFixture,
) -> None:
    with PlayJab(timeout=_TIMEOUT_MS) as api:
        window = api.attach(hwnd=swing_fixture.hwnd).window()
        tabs = window.get_by_name("fixture.tabs")
        tabs.select_option(3)
        try:
            rendered_list = window.get_by_name("fixture.custom_rendered_list")
            items = rendered_list.get_by_role("label").all()
            names = [item.snapshot().name for item in items]
            assert names == ["#0: Alpha", "#1: Beta", "#2: Gamma"]
            assert api.live_ref_count == 0
        finally:
            tabs.select_option(0)
