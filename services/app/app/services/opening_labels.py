"""Opening label generation service for display-friendly opening names.

Extracts opening names from PGN headers, Lichess database, ECO codes, and fallback
heuristics when standard catalogs are unavailable.
"""
from __future__ import annotations

import io
import re
from urllib.parse import unquote, urlparse

import chess.pgn

_ROUND_SUFFIX_RE = re.compile(r"\s+-\s+Round\b.*$", re.IGNORECASE)
_OPENING_HINT_RE = re.compile(
    r"opening|defense|gambit|attack|variation|system|indian|sicilian|pirc|reti|benoni|slav|catalan|french|caro|nimzo",
    re.IGNORECASE,
)
_URL_MOVE_SUFFIX_RE = re.compile(r"\s+\d+\.(?:\.\.)?\S.*$")
_MOVE_TOKEN_RE = re.compile(
    r"^(?:O-O(?:-O)?|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?|[a-h]x[a-h][1-8](?:=[QRBN])?|[a-h][1-8])$"
)


def _event_label(event: str) -> str | None:
    """Extract opening name from PGN Event header if it contains opening keywords."""
    text = _ROUND_SUFFIX_RE.sub("", (event or "").strip()).strip()
    if not text:
        return None
    if _OPENING_HINT_RE.search(text):
        return text
    return None


def _ecourl_label(ecourl: str) -> str | None:
    """Extract opening name from Lichess ECOUrl header; URL slug to readable name."""
    path = urlparse((ecourl or "").strip()).path.rstrip("/")
    slug = unquote(path.rsplit("/", 1)[-1]) if path else ""
    if not slug:
        return None
    if slug.lower() == "undefined":
        return "Undefined Opening"
    label = slug.replace("-", " ").strip()
    label = _URL_MOVE_SUFFIX_RE.sub("", label).strip()
    return label or None


def _prefix_eco(label: str, eco_code: str | None) -> str:
    """Prepend ECO code to label if not already present."""
    eco = (eco_code or "").strip()
    text = (label or "").strip()
    if eco and text and not text.startswith(eco):
        return f"{eco} {text}"
    return text


def _looks_like_move_sequence(label: str) -> bool:
    """Detect if label is move notation rather than opening name."""
    tokens = [token.rstrip("+#!?") for token in (label or "").split() if token.strip()]
    if len(tokens) < 3:
        return False
    if _OPENING_HINT_RE.search(label or ""):
        return False
    move_like = sum(1 for token in tokens if _MOVE_TOKEN_RE.fullmatch(token))
    return move_like / len(tokens) >= 0.7


def _uncatalogued_label(eco_code: str | None, pgn_text: str | None) -> str | None:
    """Generate fallback label from PGN headers when standard catalogs unavailable."""
    text = str(pgn_text or "").strip()
    if not text:
        return _prefix_eco("Uncatalogued Opening", eco_code) or None

    game = chess.pgn.read_game(io.StringIO(text))
    if game is None:
        return _prefix_eco("Uncatalogued Opening", eco_code) or None

    headers = game.headers
    setup = (headers.get("SetUp") or "").strip() == "1"
    event_label = _event_label(headers.get("Event") or "")
    ecourl_label = _ecourl_label(headers.get("ECOUrl") or "")
    move_count = sum(1 for _ in game.mainline_moves())

    if setup:
        source = ecourl_label or event_label
        if source and source != "Undefined Opening":
            return _prefix_eco(f"{source} (Setup)", eco_code)
        return _prefix_eco("Custom Start Position", eco_code)

    if move_count == 0:
        return _prefix_eco("No Moves Recorded", eco_code)

    if ecourl_label and ecourl_label != "Undefined Opening":
        return _prefix_eco(ecourl_label, eco_code)

    if event_label:
        return _prefix_eco(event_label, eco_code)

    if ecourl_label == "Undefined Opening":
        return _prefix_eco("Undefined Opening", eco_code)

    return _prefix_eco("Uncatalogued Opening", eco_code)


def opening_display_label(
    eco_code: str | None,
    lichess_opening: str | None,
    opening_name: str | None,
    pgn_text: str | None = None,
) -> str:
    eco = (eco_code or "").strip()
    lichess = (lichess_opening or "").strip()
    opening = (opening_name or "").strip()

    if lichess:
        return lichess

    if opening and opening.lower() != "unknown" and not _looks_like_move_sequence(opening):
        return _prefix_eco(opening, eco)

    fallback = _uncatalogued_label(eco, pgn_text)
    if fallback:
        return fallback

    return _prefix_eco("Unknown Opening", eco) or "Unknown Opening"