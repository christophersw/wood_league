"""
Title: test_move_annotations.py — Tests for the move-annotation source of truth
Description:
    Verifies the ANNOTATIONS dict shape, the symbol() / title() helpers,
    and that all eight SF classifications used elsewhere in the app
    (brilliant, best, great, excellent, good, inaccuracy, mistake, blunder)
    are present so server-rendered badges never silently drop a class.

Changelog:
    2026-05-26 (#212): Initial — guards the new annotation single source of truth.
"""
import pytest
from django.template import Context, Template
from django.template.loader import render_to_string

from games.move_annotations import ANNOTATIONS, symbol, title


CANONICAL_CLASSIFICATIONS = (
    "brilliant", "best", "great", "excellent",
    "good", "inaccuracy", "mistake", "blunder",
)


def test_annotations_dict_covers_every_sf_classification():
    """Every classification used by _card_sf.html and the move classifier must be present."""
    for cls in CANONICAL_CLASSIFICATIONS:
        assert cls in ANNOTATIONS, f"ANNOTATIONS missing key: {cls}"


def test_annotations_entries_have_symbol_and_title_keys():
    """Each entry must expose both symbol and title (symbol may be empty string)."""
    for cls, entry in ANNOTATIONS.items():
        assert "symbol" in entry, f"{cls} missing symbol key"
        assert "title" in entry, f"{cls} missing title key"
        assert isinstance(entry["symbol"], str)
        assert isinstance(entry["title"], str)


@pytest.mark.parametrize("classification,expected", [
    ("brilliant", "!!"),
    ("great", "!"),
    ("inaccuracy", "?!"),
    ("mistake", "?"),
    ("blunder", "??"),
])
def test_symbol_returns_canonical_value_for_classified_moves(classification, expected):
    """The five badge-bearing classifications return their canonical symbol."""
    assert symbol(classification) == expected


@pytest.mark.parametrize("classification", ["best", "excellent", "good"])
def test_symbol_returns_empty_string_for_unbadged_classifications(classification):
    """Best/excellent/good have no badge — symbol() returns empty string."""
    assert symbol(classification) == ""


def test_symbol_returns_empty_string_for_none():
    """A None classification (unanalyzed move) yields no symbol."""
    assert symbol(None) == ""


def test_symbol_returns_empty_string_for_unknown_classification():
    """An unknown classification gracefully degrades rather than KeyError'ing."""
    assert symbol("not-a-real-class") == ""


def test_symbol_is_case_insensitive():
    """Callers may pass mixed-case classifications (DB normalisation is not guaranteed)."""
    assert symbol("Blunder") == "??"
    assert symbol("BLUNDER") == "??"


def test_title_returns_human_readable_label():
    """title() returns the human-readable label for tooltip use."""
    assert title("blunder") == "Blunder"
    assert title("inaccuracy") == "Inaccuracy"


def test_title_falls_back_to_classification_when_unknown():
    """Unknown classification → return the input unchanged so the user still sees something."""
    assert title("some-future-class") == "some-future-class"


def test_title_returns_empty_string_for_none():
    """A None classification (unanalyzed move) yields no title."""
    assert title(None) == ""


# --- Template-tag filter tests ---


def _render(template_source: str, context: dict) -> str:
    """Render a template fragment with {% load games_extras %} for filter tests.

    Parameters:
        template_source (str): The template body (without the load tag).
        context (dict): The render context.

    Returns:
        str: The rendered output.
    """
    full = "{% load games_extras %}" + template_source
    return Template(full).render(Context(context))


def test_move_annotation_symbol_filter_returns_canonical_symbol():
    """The filter exposes symbol() to templates."""
    out = _render("{{ cls|move_annotation_symbol }}", {"cls": "blunder"})
    assert out == "??"


def test_move_annotation_symbol_filter_returns_empty_for_none():
    """None classification renders as empty string (no badge)."""
    out = _render("{{ cls|move_annotation_symbol }}", {"cls": None})
    assert out == ""


def test_move_annotation_title_filter_returns_human_label():
    """The filter exposes title() to templates."""
    out = _render("{{ cls|move_annotation_title }}", {"cls": "inaccuracy"})
    assert out == "Inaccuracy"


def test_move_annotation_title_filter_falls_back_to_classification():
    """Unknown classification → renders the input unchanged."""
    out = _render("{{ cls|move_annotation_title }}", {"cls": "future-class"})
    assert out == "future-class"


# --- Include rendering tests ---


def test_move_annotation_include_renders_badge_for_classified_move():
    """The include emits a move-annotation span with the right class for a classified move."""
    out = render_to_string(
        "games/partials/_move_annotation.html",
        {"classification": "blunder"},
    )
    assert 'class="move-annotation move-annotation-blunder"' in out
    assert ">??<" in out
    assert 'title="Blunder"' in out


def test_move_annotation_include_renders_nothing_for_unbadged_move():
    """No symbol → no badge element at all (best/excellent/good have no symbol)."""
    out = render_to_string(
        "games/partials/_move_annotation.html",
        {"classification": "best"},
    )
    assert "move-annotation" not in out


def test_move_annotation_include_renders_nothing_for_none():
    """None classification → no badge element."""
    out = render_to_string(
        "games/partials/_move_annotation.html",
        {"classification": None},
    )
    assert out.strip() == ""


def test_move_annotation_include_lowercases_class_suffix():
    """Mixed-case classification produces a lowercase CSS class suffix."""
    out = render_to_string(
        "games/partials/_move_annotation.html",
        {"classification": "Blunder"},
    )
    assert "move-annotation-blunder" in out
