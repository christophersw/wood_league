"""Search services: AI-powered SQL generation and keyword search."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import requests
from django.conf import settings
from django.db import connection

from games.models import Game, GameParticipant
from players.models import Player

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
MAX_RESULTS = 200


@dataclass(frozen=True)
class SearchPlan:
    """Result of AI-generated search plan containing SQL query and reasoning."""

    sql_query: str
    reasoning: str = ""
    raw_response: str = ""
    candidate_sql: str = ""


class SearchPlanError(ValueError):
    """Exception raised when AI search plan generation or validation fails."""

    def __init__(
        self,
        message: str,
        *,
        raw_response: str = "",
        reasoning: str = "",
        candidate_sql: str = "",
    ):
        """Initialize SearchPlanError with message and optional debug fields."""
        super().__init__(message)
        self.raw_response = raw_response
        self.reasoning = reasoning
        self.candidate_sql = candidate_sql


@lru_cache(maxsize=1)
def _schema_context() -> str:
    """Return cached database schema context for AI SQL generation."""
    return """
You convert natural-language game search requests into safe PostgreSQL SELECT queries.
Return JSON only with keys: sql_query, reasoning.

STRICT RULES:
- One SELECT statement only.
- No INSERT/UPDATE/DELETE/DDL.
- Allowed tables only: `games`, `game_analysis`, `move_analysis`, `game_participants`.
- JOIN is allowed only between allowed tables.
- No UNION, INTERSECT, EXCEPT.
- Prefer selecting game-level rows from `games` (or `games` + `game_analysis`) unless the user explicitly asks for move-level analysis.
- Use LIMIT <= 200.
- Use ILIKE for fuzzy text search on names and openings.
- For recent games, order by played_at DESC.
- Always include games.id and games.slug in the SELECT.

Schema:
CREATE TABLE games (
  id VARCHAR(64) PRIMARY KEY,
  slug VARCHAR(80),
  played_at TIMESTAMP,
  white_username VARCHAR(120),
  black_username VARCHAR(120),
  white_rating INTEGER,
  black_rating INTEGER,
  result_pgn VARCHAR(16),        -- '1-0', '0-1', '1/2-1/2'
  winner_username VARCHAR(120),  -- NULL for draws
  time_control VARCHAR(32),
  eco_code VARCHAR(8),
  opening_name VARCHAR(120),
  lichess_opening VARCHAR(200),
  pgn TEXT
);

CREATE TABLE game_analysis (
    id INTEGER PRIMARY KEY,
    game_id VARCHAR(64) UNIQUE REFERENCES games(id),
    summary_cp FLOAT,
    analyzed_at TIMESTAMP,
    engine_depth INTEGER,
    white_accuracy FLOAT,
    black_accuracy FLOAT,
    white_acpl FLOAT,
    black_acpl FLOAT,
    white_blunders INTEGER,
    white_mistakes INTEGER,
    white_inaccuracies INTEGER,
    black_blunders INTEGER,
    black_mistakes INTEGER,
    black_inaccuracies INTEGER
);

CREATE TABLE move_analysis (
    id INTEGER PRIMARY KEY,
    analysis_id INTEGER REFERENCES game_analysis(id),
    ply INTEGER,
    san VARCHAR(32),
    fen TEXT,
    cp_eval FLOAT,
    best_move VARCHAR(32),
    arrow_uci VARCHAR(8),
    cpl FLOAT,
    classification VARCHAR(16)
);

CREATE TABLE game_participants (
    id INTEGER PRIMARY KEY,
    game_id VARCHAR(64) REFERENCES games(id),
    player_id INTEGER,
    color VARCHAR(8),
    opponent_username VARCHAR(120),
    player_rating INTEGER,
    opponent_rating INTEGER,
    result VARCHAR(32),
    quality_score FLOAT,
    blunder_count INTEGER,
    mistake_count INTEGER,
    inaccuracy_count INTEGER,
    acpl FLOAT
);

JOIN KEYS:
- game_analysis.game_id = games.id
- move_analysis.analysis_id = game_analysis.id
- game_participants.game_id = games.id

KEY DATA RULES:
- winner_username is the username of the player who won. It is NULL for draws.
- To find games a player WON: winner_username ILIKE '%player%'
- To find games a player LOST: (white_username ILIKE '%player%' OR black_username ILIKE '%player%') AND winner_username IS NOT NULL AND winner_username NOT ILIKE '%player%'
- To find ALL games involving a player: check BOTH white_username and black_username.
- To find draws: result_pgn = '1/2-1/2' or winner_username IS NULL.
- Usernames are case-insensitive Chess.com handles. Always use ILIKE.

Example queries:

-- All games player won:
SELECT id, slug, played_at, white_username, black_username, result_pgn, lichess_opening FROM games
WHERE winner_username ILIKE '%chris%' ORDER BY played_at DESC LIMIT 100

-- Games with accuracy:
SELECT g.id, g.slug, g.played_at, g.white_username, g.black_username,
       ga.white_accuracy, ga.black_accuracy
FROM games g
JOIN game_analysis ga ON ga.game_id = g.id
WHERE ga.analyzed_at IS NOT NULL ORDER BY g.played_at DESC LIMIT 100

-- All draws:
SELECT id, slug, played_at, white_username, black_username FROM games
WHERE result_pgn = '1/2-1/2' ORDER BY played_at DESC LIMIT 100

COMMON OPENING NAMES (lichess_opening column):
Scandinavian Defense, Pirc Defense, Philidor Defense, Caro-Kann Defense,
Bishop's Opening, Scotch Game, Sicilian Defense, Italian Game, French Defense,
Ruy Lopez, Petrov's Defense, English Opening, King's Indian Attack
""".strip()


def _player_directory_context() -> str:
    """Build list of club players for AI prompt context."""
    rows = Player.objects.values("username", "display_name").order_by("username")[:100]
    if not rows:
        return "Known club players: none loaded."
    lines = [
        "KNOWN CLUB PLAYERS:",
        "- Map mentions of first names, display names, and possessive forms to these usernames.",
        "- Generate filters against games.white_username, games.black_username, or games.winner_username.",
    ]
    for row in rows:
        username = (row["username"] or "").strip()
        display_name = (row["display_name"] or "").strip()
        if not username:
            continue
        if display_name and display_name.lower() != username.lower():
            lines.append(f"- username: {username}; display_name: {display_name}")
        else:
            lines.append(f"- username: {username}")
    return "\n".join(lines)


def is_ai_available() -> bool:
    """Check if Anthropic API key is configured."""
    return bool(getattr(settings, "ANTHROPIC_API_KEY", "").strip())


def _extract_text(response_json: dict) -> str:
    """Extract text content from Anthropic API response."""
    return "\n".join(
        item.get("text", "")
        for item in response_json.get("content", [])
        if item.get("type") == "text"
    ).strip()


def _extract_json(raw_text: str) -> dict:
    """Parse JSON from Claude response, handling markdown code blocks."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("Response did not contain valid JSON.")
    return json.loads(cleaned[start : end + 1])  # noqa: E203


def _sanitize_sql(candidate_sql: str) -> str:
    """Validate and sanitize SQL query to prevent injection and unsafe operations."""
    if not candidate_sql:
        raise ValueError("No SQL was generated.")
    sql = candidate_sql.strip()
    if sql.startswith("```"):
        sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\s*```$", "", sql)
    sql = sql.strip().rstrip(";").strip()
    if ";" in sql:
        raise ValueError("Only one SQL statement is allowed.")
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise ValueError("SQL comments are not allowed.")
    lowered = sql.lower()
    if not lowered.startswith("select"):
        raise ValueError("Only SELECT statements are allowed.")
    if re.search(r"^\s*with\b", lowered):
        raise ValueError("WITH queries are not allowed.")
    if re.search(r"\binto\b", lowered):
        raise ValueError("SELECT ... INTO is not allowed.")
    for term in ["insert", "update", "delete", "drop", "alter", "truncate", "grant", "revoke", "create", "copy", "merge"]:
        if re.search(rf"\b{term}\b", lowered):
            raise ValueError(f"Unsafe SQL keyword detected: {term}")
    if re.search(r"\b(union|intersect|except)\b", lowered):
        raise ValueError("UNION/INTERSECT/EXCEPT are not allowed.")
    if re.search(r"\b(pg_catalog|information_schema)\b", lowered):
        raise ValueError("System catalog access is not allowed.")
    if re.search(r"\bpg_[a-z0-9_]+\b", lowered):
        raise ValueError("Postgres system functions are not allowed.")

    allowed_tables = {"games", "game_analysis", "move_analysis", "game_participants"}
    table_refs = re.findall(
        r"\b(?:from|join)\s+(?:\"?[a-z_][a-z0-9_]*\"?\.)?\"?([a-z_][a-z0-9_]*)\"?",
        lowered,
    )
    if not table_refs:
        raise ValueError("Query must include a FROM clause.")
    disallowed = sorted({t for t in table_refs if t not in allowed_tables})
    if disallowed:
        raise ValueError(f"Query references disallowed table(s): {', '.join(disallowed)}")

    limit_match = re.search(r"\blimit\s+(\d+)\b", sql, flags=re.IGNORECASE)
    if limit_match:
        if int(limit_match.group(1)) > MAX_RESULTS:
            sql = re.sub(r"\blimit\s+\d+\b", f"LIMIT {MAX_RESULTS}", sql, flags=re.IGNORECASE)
    else:
        sql = f"{sql} LIMIT {MAX_RESULTS}"
    return sql


def generate_search_plan(user_query: str) -> SearchPlan:
    """Generate SQL search plan using Claude AI from natural language query."""
    query = user_query.strip()
    if not query:
        raise ValueError("Please enter a search query.")
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise SearchPlanError("ANTHROPIC_API_KEY is not configured.")

    payload = {
        "model": DEFAULT_ANTHROPIC_MODEL,
        "max_tokens": 500,
        "temperature": 0,
        "system": [
            {"type": "text", "text": "You generate safe SQL search plans for chess games. Return JSON only with sql_query and reasoning."},
            {"type": "text", "text": _schema_context(), "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": _player_directory_context(), "cache_control": {"type": "ephemeral"}},
        ],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": f"User request:\n{query}\n\nReturn only JSON with sql_query and reasoning."}]},
        ],
    }
    try:
        response = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "prompt-caching-2024-07-31",
                "content-type": "application/json",
            },
            json=payload,
            timeout=45,
        )
    except requests.RequestException as exc:
        raise SearchPlanError(f"Network error calling Anthropic: {exc}") from exc

    if not response.ok:
        raise SearchPlanError(f"Anthropic API error {response.status_code}: {response.text[:400]}")

    raw_text = _extract_text(response.json())
    if not raw_text:
        raise SearchPlanError("Claude returned an empty response.")

    try:
        parsed = _extract_json(raw_text)
    except Exception as exc:
        raise SearchPlanError("Claude did not return valid JSON.", raw_response=raw_text) from exc

    reasoning = str(parsed.get("reasoning", "")).strip()
    candidate_sql = str(parsed.get("sql_query", "")).strip()

    try:
        sql_query = _sanitize_sql(candidate_sql)
    except Exception as exc:
        raise SearchPlanError(str(exc), raw_response=raw_text, reasoning=reasoning, candidate_sql=candidate_sql) from exc

    return SearchPlan(sql_query=sql_query, reasoning=reasoning, raw_response=raw_text, candidate_sql=candidate_sql)


def execute_sql_search(sql_query: str) -> list[dict[str, Any]]:
    """Execute sanitized SQL query and return results as list of dictionaries."""
    safe_sql = _sanitize_sql(sql_query)
    with connection.cursor() as cursor:
        cursor.execute(safe_sql)
        cols = [col[0] for col in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def keyword_game_search(query: str, limit: int = 200) -> list[dict[str, Any]]:
    """Search games by keyword in players, openings, and time controls."""
    q = query.strip()
    if not q:
        return []
    like = f"%{q}%"
    qs = (
        Game.objects.filter(
            white_username__icontains=q,
        )
        | Game.objects.filter(black_username__icontains=q)
        | Game.objects.filter(opening_name__icontains=q)
        | Game.objects.filter(lichess_opening__icontains=q)
        | Game.objects.filter(eco_code__icontains=q)
        | Game.objects.filter(time_control__icontains=q)
    )
    qs = qs.order_by("-played_at")[:limit]
    return [
        {
            "game_id": g.id,
            "slug": g.slug,
            "played_at": g.played_at.strftime("%Y-%m-%d") if g.played_at else "",
            "white_username": g.white_username or "",
            "black_username": g.black_username or "",
            "result_pgn": g.result_pgn or "",
            "opening": g.lichess_opening or g.opening_name or "",
            "time_control": g.time_control or "",
        }
        for g in qs
    ]
