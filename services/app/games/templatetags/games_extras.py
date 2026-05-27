"""
Title: games_extras.py — Custom template filters for the games app
Description:
    Exposes move_annotation_symbol and move_annotation_title as Django
    template filters so partials/_move_annotation.html can render badge
    spans server-side without duplicating the annotation map.

    Both filters delegate to games.move_annotations and accept None
    (for unanalyzed moves) without raising.

Changelog:
    2026-05-26 (#212): Initial — created to back the moves-strip annotation include.
"""
from django import template

from games import move_annotations

register = template.Library()


@register.filter(name="move_annotation_symbol")
def move_annotation_symbol(classification: str | None) -> str:
    """
    Template filter: return the badge symbol for a classification, or "".

    Parameters:
        classification (str | None): SF classification label.

    Returns:
        str: The canonical badge symbol or empty string.
    """
    return move_annotations.symbol(classification)


@register.filter(name="move_annotation_title")
def move_annotation_title(classification: str | None) -> str:
    """
    Template filter: return the tooltip title for a classification.

    Parameters:
        classification (str | None): SF classification label.

    Returns:
        str: The human-readable title or empty string.
    """
    return move_annotations.title(classification)
