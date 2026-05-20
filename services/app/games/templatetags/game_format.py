"""
Title: game_format.py — Template tags for the search results table and modal
Description:
    Filters and tags used by ``templates/search/`` to render human time
    controls, truncated opening notation, accuracy bands, and
    club-member accuracy chips on the search results table and the
    game preview modal.

Changelog:
    2026-05-20: Initial creation (#162).
"""
from __future__ import annotations

from django import template

from games.opening_notation import opening_notation as _opening_notation
from games.time_control_format import format_time_control

register = template.Library()


def _read(obj, name):
    """Return ``obj[name]`` for dicts, ``getattr`` for everything else.

    Args:
        obj: A dict or any object.
        name: The key/attribute name to read.

    Returns:
        The value at ``name``, or ``None`` if absent.
    """
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


@register.filter(name="time_control_human")
def time_control_human(game) -> str:
    """Render a Game's time control as a human label.

    Accepts either a Django Game model or a dict row from the search
    pipeline; reads ``time_control_base_s``, ``time_control_increment_s``,
    and the raw ``time_control`` string as a fallback.

    Args:
        game: Game model instance or dict with time control fields.

    Returns:
        Human-readable label such as ``"15+10 min"`` or ``"3 min"``.
    """
    return format_time_control(
        _read(game, "time_control_base_s"),
        _read(game, "time_control_increment_s"),
        raw=_read(game, "time_control") or "",
    )


@register.filter(name="opening_notation")
def opening_notation_filter(pgn_text: str, max_plies: int = 10) -> str:
    """Render the first ``max_plies`` plies of a PGN as SAN.

    Args:
        pgn_text: Raw PGN string.
        max_plies: Maximum number of half-moves to include (default 10).

    Returns:
        SAN string for the opening moves, e.g. ``"1. e4 e5 2. Nf3 Nc6"``.
    """
    return _opening_notation(pgn_text or "", max_plies=max_plies)


_BANDS = (
    (90, "wc-chip--band-strong"),
    (80, "wc-chip--band-good"),
    (70, "wc-chip--band-fair"),
    (60, "wc-chip--band-weak"),
)


@register.filter(name="accuracy_band_class")
def accuracy_band_class(accuracy) -> str:
    """Return the Tailwind chip class string for an accuracy value.

    ``None`` → unknown; below 60 → poor. The colour-token bindings live
    in static/css/main.css under ``@layer components``.

    Args:
        accuracy: Numeric accuracy percentage (0–100) or ``None``.

    Returns:
        Space-separated class string, e.g. ``"wc-chip wc-chip--band-good"``.
    """
    if accuracy is None:
        return "wc-chip wc-chip--band-unknown"
    for floor, cls in _BANDS:
        if accuracy >= floor:
            return f"wc-chip {cls}"
    return "wc-chip wc-chip--band-poor"


def _avg(*vals):
    """Mean of the non-None inputs, or ``None`` if all are ``None``.

    Args:
        *vals: Numeric values or ``None``.

    Returns:
        Float mean of non-None values, or ``None`` when all inputs are ``None``.
    """
    present = [v for v in vals if v is not None]
    return sum(present) / len(present) if present else None


def club_accuracy_chips(
    *,
    white_username: str | None,
    black_username: str | None,
    club_usernames: dict[str, str],
    sf_white: float | None,
    sf_black: float | None,
    lc0_white: float | None,
    lc0_black: float | None,
) -> list[dict]:
    """Build chip data for each side that is a club member.

    Args:
        white_username: Game's recorded white-side username.
        black_username: Game's recorded black-side username.
        club_usernames: Mapping of ``username → display_name`` for club
            members (matched case-insensitively).
        sf_white: Stockfish accuracy % for white; ``None`` if unavailable.
        sf_black: Stockfish accuracy % for black; ``None`` if unavailable.
        lc0_white: Lc0 accuracy % for white; ``None`` if unavailable.
        lc0_black: Lc0 accuracy % for black; ``None`` if unavailable.

    Returns:
        Zero, one, or two dicts — one per club-member side. Each carries
        ``display_name``, ``sf``, ``lc0`` (any may be ``None``) and a
        ``band_class`` derived from the mean of engines that reported.
    """
    club_lower = {k.lower(): v for k, v in (club_usernames or {}).items()}
    sides = (
        (white_username, sf_white, lc0_white),
        (black_username, sf_black, lc0_black),
    )
    chips: list[dict] = []
    for username, sf, lc0 in sides:
        if not username:
            continue
        display = club_lower.get(username.lower())
        if not display:
            continue
        chips.append({
            "display_name": display,
            "sf": sf,
            "lc0": lc0,
            "band_class": accuracy_band_class(_avg(sf, lc0)),
        })
    return chips


@register.simple_tag(name="club_accuracy_chips")
def club_accuracy_chips_tag(
    *,
    white_username,
    black_username,
    club_usernames,
    sf_white=None,
    sf_black=None,
    lc0_white=None,
    lc0_black=None,
):
    """Template wrapper around :func:`club_accuracy_chips`.

    Args:
        white_username: White-side username string.
        black_username: Black-side username string.
        club_usernames: Dict mapping username → display name.
        sf_white: Stockfish accuracy for white (optional).
        sf_black: Stockfish accuracy for black (optional).
        lc0_white: Lc0 accuracy for white (optional).
        lc0_black: Lc0 accuracy for black (optional).

    Returns:
        List of chip dicts (see :func:`club_accuracy_chips`).
    """
    return club_accuracy_chips(
        white_username=white_username,
        black_username=black_username,
        club_usernames=club_usernames,
        sf_white=sf_white,
        sf_black=sf_black,
        lc0_white=lc0_white,
        lc0_black=lc0_black,
    )
