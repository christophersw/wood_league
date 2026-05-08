"""Game search service using Claude AI to parse natural language queries into SQL.

Translates user game search requests into parameterized SQL queries with sanitization,
supports keyword search, and integrates with Anthropic API for NL-to-SQL generation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import pandas as pd
import requests
from sqlalchemy import or_, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.services.history_service import HistoryFilters, HistoryService
from app.services.opening_labels import opening_display_label
from app.storage.database import get_session, init_db
from app.storage.models import Game, GameAnalysis, GameParticipant, Player

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_ANTHROPIC_MODEL = "claude-3-haiku-20240307"
MAX_RESULTS = 200


@dataclass(frozen=True)
class SearchPlan:
    """Immutable result of Claude-generated search plan with SQL and reasoning."""
    sql_query: str
    reasoning: str = ""
    raw_response: str = ""
    candidate_sql: str = ""
    parsed_plan: dict[str, Any] | None = None


class SearchPlanError(ValueError):
    """Exception for search plan generation or validation failures with context."""
    def __init__(
        self,
        message: str,
        *,
        raw_response: str = "",
        parsed_plan: dict[str, Any] | None = None,
        reasoning: str = "",
        candidate_sql: str = "",
    ):
        super().__init__(message)
        self.raw_response = raw_response
        self.parsed_plan = parsed_plan or {}
        self.reasoning = reasoning
        self.candidate_sql = candidate_sql


@lru_cache(maxsize=1)
def _schema_context() -> str:
    """Return cached database schema and SQL generation rules for Claude prompt."""
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

Schema:
CREATE TABLE games (
  id VARCHAR(64) PRIMARY KEY,
  played_at TIMESTAMP,
  white_username VARCHAR(120),   -- Chess.com username of white player
  black_username VARCHAR(120),   -- Chess.com username of black player
  white_rating INTEGER,
  black_rating INTEGER,
  result_pgn VARCHAR(16),        -- PGN result: '1-0' (white wins), '0-1' (black wins), '1/2-1/2' (draw)
  winner_username VARCHAR(120),  -- username of the winner, NULL for draws
  time_control VARCHAR(32),      -- e.g. '600', '180+2', '900+10'
  eco_code VARCHAR(8),           -- e.g. 'B90', 'C50'
  opening_name VARCHAR(120),     -- Chess.com opening name, e.g. 'Sicilian Defense'
  lichess_opening VARCHAR(200),  -- Lichess opening name (more specific), e.g. 'Sicilian Defense: Najdorf Variation'
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
- To find games a player LOST: they played (white or black) but did NOT win:
    (white_username ILIKE '%player%' OR black_username ILIKE '%player%')
    AND winner_username IS NOT NULL AND winner_username NOT ILIKE '%player%'
- To find ALL games involving a player: check BOTH white_username and black_username.
- To find draws: result_pgn = '1/2-1/2' or winner_username IS NULL.
- Usernames are case-insensitive Chess.com handles. Always use ILIKE for matching.

Example queries:

-- All games player "chris" won:
SELECT * FROM games
WHERE winner_username ILIKE '%chris%'
ORDER BY played_at DESC LIMIT 100

-- Games chris won against breakhappy:
SELECT * FROM games
WHERE winner_username ILIKE '%chris%'
  AND (white_username ILIKE '%breakhappy%' OR black_username ILIKE '%breakhappy%')
ORDER BY played_at DESC LIMIT 100

-- Games chris lost against breakhappy:
SELECT * FROM games
WHERE winner_username ILIKE '%breakhappy%'
  AND (white_username ILIKE '%chris%' OR black_username ILIKE '%chris%')
ORDER BY played_at DESC LIMIT 100

-- All games between two players (any result):
SELECT * FROM games
WHERE (white_username ILIKE '%chris%' AND black_username ILIKE '%breakhappy%')
   OR (white_username ILIKE '%breakhappy%' AND black_username ILIKE '%chris%')
ORDER BY played_at DESC LIMIT 100

-- All games involving a player:
SELECT * FROM games
WHERE white_username ILIKE '%hikaru%' OR black_username ILIKE '%hikaru%'
ORDER BY played_at DESC LIMIT 100

-- Losses as black in a specific opening (search both opening columns):
SELECT * FROM games
WHERE black_username ILIKE '%chris%'
  AND winner_username NOT ILIKE '%chris%'
  AND (opening_name ILIKE '%sicilian%' OR lichess_opening ILIKE '%sicilian%')
ORDER BY played_at DESC LIMIT 100

-- All Ruy Lopez games:
SELECT * FROM games
WHERE lichess_opening ILIKE '%ruy lopez%'
ORDER BY played_at DESC LIMIT 100

-- Queen's Gambit games:
SELECT * FROM games
WHERE lichess_opening ILIKE '%queen%gambit%'
ORDER BY played_at DESC LIMIT 100

-- Games in the last 30 days:
SELECT * FROM games
WHERE played_at >= NOW() - INTERVAL '30 days'
ORDER BY played_at DESC LIMIT 100

-- Games with engine accuracy (latest first):
SELECT g.id, g.played_at, g.white_username, g.black_username,
       ga.white_accuracy, ga.black_accuracy, ga.engine_depth
FROM games g
JOIN game_analysis ga ON ga.game_id = g.id
WHERE ga.analyzed_at IS NOT NULL
ORDER BY g.played_at DESC
LIMIT 100

-- Find games where white accuracy was below 60:
SELECT g.id, g.played_at, g.white_username, g.black_username, ga.white_accuracy
FROM games g
JOIN game_analysis ga ON ga.game_id = g.id
WHERE ga.white_accuracy < 60
ORDER BY g.played_at DESC
LIMIT 100

-- All draws:
SELECT * FROM games WHERE result_pgn = '1/2-1/2' ORDER BY played_at DESC LIMIT 100

COMMON OPENING NAMES (lichess_opening column, most frequent first):
Scandinavian Defense, Queen's Pawn Game: Accelerated London System, Pirc Defense,
Philidor Defense, Ponziani Opening, Caro-Kann Defense, Bishop's Opening, Czech Defense,
King's Pawn Game, Rapport-Jobava System, Queen's Pawn Game: Chigorin Variation,
Scotch Game, Sicilian Defense: Alapin Variation, Sicilian Defense: Smith-Morra Gambit,
Bishop's Opening: Ponziani Gambit, Queen's Pawn Game, King's Pawn Game: Leonardis Variation,
French Defense: Advance Variation, Queen's Pawn Game: Zukertort Variation,
Sicilian Defense: Bowdler Attack, Italian Game: Two Knights Defense,
Zukertort Opening, Englund Gambit, King's Indian Attack, French Defense: Knight Variation,
English Opening, Sicilian Defense: Old Sicilian, Caro-Kann Defense: Advance Variation,
King's Pawn Game: Wayward Queen Attack, Italian Game: Anti-Fried Liver Defense,
Hungarian Opening, Italian Game: Paris Defense, Bishop's Opening: Berlin Defense,
Scandinavian Defense: Icelandic-Palme Gambit, Modern Defense,
Italian Game: Giuoco Pianissimo, Caro-Kann Defense: Hillbilly Attack,
English Opening: Anglo-Scandinavian Defense, Italian Game, Sicilian Defense,
Petrov's Defense, Queen's Pawn Game: London System, Center Game,
Sicilian Defense: Modern Variations, Caro-Kann Defense: Exchange Variation,
Caro-Kann Defense: Classical Variation, Italian Game: Two Knights Defense,
Nimzowitsch Defense, French Defense: Steinitz Attack, Italian Game: Blackburne-Kostić Gambit,
Vienna Game: Stanley Variation, English Opening: King's English Variation,
King's Indian Attack, Sicilian Defense: Najdorf Variation,
King's Pawn Game: Damiano Defense, French Defense: Exchange Variation,
Three Knights Opening, Italian Game: Rousseau Gambit,
English Opening: Agincourt Defense, Indian Defense, Sicilian Defense: Closed,
Ruy Lopez: Berlin Defense, Petrov's Defense: Three Knights Game,
Englund Gambit Declined, Italian Game: Giuoco Pianissimo,
Caro-Kann Defense: Advance Variation: Short Variation, Van't Kruijs Opening,
Horwitz Defense, Bishop's Opening: Urusov Gambit,
French Defense: Advance Variation: Nimzowitsch System,
English Opening: Symmetrical Variation, Owen Defense,
English Opening: Reversed Closed Sicilian, Caro-Kann Defense: Endgame Offer,
Four Knights Game: Italian Variation, Indian Defense,
King's Pawn Game: Kiddie Countergambit, French Defense,
Italian Game: Classical Variation: Giuoco Pianissimo

When users mention an opening by name, use ILIKE with %name% on the lichess_opening column.
Use broad matches — e.g. '%sicilian%' for any Sicilian, '%caro%kann%' for Caro-Kann.
""".strip()


def _player_directory_context() -> str:
    """Return a compact prompt fragment with known club player identities.

    The SQL planner can only query the allowed game tables, so we provide a
    username/display-name directory here and instruct it to map human names
    back to usernames when generating SQL.
    """
    init_db()
    with get_session() as session:
        rows = session.execute(
            select(Player.username, Player.display_name).order_by(Player.username)
        ).all()

    if not rows:
        return "Known club players: none loaded."

    lines = [
        "KNOWN CLUB PLAYERS:",
        "- Map mentions of first names, display names, and possessive forms to these usernames.",
        "- Generate filters against games.white_username, games.black_username, or games.winner_username.",
        "- If one player clearly matches, prefer that exact username in the SQL.",
        "- If a name could refer to multiple known usernames, include OR conditions for each likely username.",
    ]

    for row in rows[:100]:
        username = (row.username or "").strip()
        display_name = (row.display_name or "").strip()
        if not username:
            continue
        if display_name and display_name.lower() != username.lower():
            lines.append(f"- username: {username}; display_name: {display_name}")
        else:
            lines.append(f"- username: {username}")

    return "\n".join(lines)


def is_anthropic_available() -> bool:
    """Check if Anthropic API key is configured."""
    return bool(get_settings().anthropic_api_key.strip())


def get_anthropic_model() -> str:
    """Get configured Anthropic model or default to Haiku."""
    configured = get_settings().anthropic_model.strip()
    return configured or DEFAULT_ANTHROPIC_MODEL


def _extract_text(response_json: dict[str, Any]) -> str:
    """Extract text content from Anthropic API response."""
    parts = []
    for item in response_json.get("content", []):
        if item.get("type") == "text":
            parts.append(item.get("text", ""))
    return "\n".join([p for p in parts if p]).strip()


def _extract_json(raw_text: str) -> dict[str, Any]:
    """Parse JSON from text, handling markdown code blocks."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Claude did not return valid JSON.")
    return json.loads(cleaned[start : end + 1])


def _sanitize_sql(candidate_sql: str) -> str:
    """Validate and sanitize SQL to prevent injection; enforce allowed tables and LIMIT."""
    if not candidate_sql:
        raise ValueError("Claude did not generate SQL.")

    sql = candidate_sql.strip()
    if sql.startswith("```"):
        sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\s*```$", "", sql)

    sql = sql.strip().rstrip(";").strip()
    if ";" in sql:
        raise ValueError("Only one SQL statement is allowed.")

    # Disallow inline/block comments to prevent hidden payloads.
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise ValueError("SQL comments are not allowed.")

    lowered = sql.lower()
    if not lowered.startswith("select"):
        raise ValueError("Only SELECT is allowed.")

    # CTEs and INTO can mask multi-step behavior. Keep generated SQL simple.
    if re.search(r"^\s*with\b", lowered):
        raise ValueError("WITH queries are not allowed.")
    if re.search(r"\binto\b", lowered):
        raise ValueError("SELECT ... INTO is not allowed.")

    blocked_terms = [
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "truncate",
        "grant",
        "revoke",
        "create",
        "copy",
        "merge",
    ]
    for term in blocked_terms:
        if re.search(rf"\b{term}\b", lowered):
            raise ValueError(f"Unsafe SQL keyword: {term}")

    if re.search(r"\b(union|intersect|except)\b", lowered):
        raise ValueError("UNION/INTERSECT/EXCEPT are not allowed.")

    # Block references to database/system catalogs.
    if re.search(r"\b(pg_catalog|information_schema)\b", lowered):
        raise ValueError("System catalog access is not allowed.")
    if re.search(r"\bpg_[a-z0-9_]+\b", lowered):
        raise ValueError("Postgres system functions are not allowed.")

    allowed_tables = {
        "games",
        "game_analysis",
        "move_analysis",
        "game_participants",
    }
    table_refs = re.findall(
        r"\b(?:from|join)\s+(?:\"?[a-z_][a-z0-9_]*\"?\.)?\"?([a-z_][a-z0-9_]*)\"?",
        lowered,
        flags=re.IGNORECASE,
    )
    if not table_refs:
        raise ValueError("Query must include a FROM clause.")

    disallowed = sorted({t for t in table_refs if t not in allowed_tables})
    if disallowed:
        raise ValueError(
            f"Query references disallowed table(s): {', '.join(disallowed)}"
        )

    limit_match = re.search(r"\blimit\s+(\d+)\b", sql, flags=re.IGNORECASE)
    if limit_match:
        n = int(limit_match.group(1))
        if n > MAX_RESULTS:
            sql = re.sub(
                r"\blimit\s+\d+\b", f"LIMIT {MAX_RESULTS}", sql, flags=re.IGNORECASE
            )
    else:
        sql = f"{sql} LIMIT {MAX_RESULTS}"

    return sql


def generate_search_plan(user_query: str) -> SearchPlan:
    """Call Anthropic API to translate user query into sanitized SQL search plan."""
    query = user_query.strip()
    if not query:
        raise ValueError("Please enter a search query.")

    api_key = get_settings().anthropic_api_key.strip()
    if not api_key:
        raise SearchPlanError("ANTHROPIC_API_KEY is not configured.")

    payload = {
        "model": get_anthropic_model(),
        "max_tokens": 500,
        "temperature": 0,
        "system": [
            {
                "type": "text",
                "text": (
                    "You generate safe SQL search plans for games. "
                    "Return JSON only with sql_query and reasoning."
                ),
            },
            {
                "type": "text",
                "text": _schema_context(),
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": _player_directory_context(),
                "cache_control": {"type": "ephemeral"},
            },
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "User request:\n"
                            f"{query}\n\n"
                            "Return only JSON with sql_query and reasoning."
                        ),
                    }
                ],
            }
        ],
    }

    response = requests.post(
        ANTHROPIC_API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=payload,
        timeout=45,
    )
    if not response.ok:
        raise SearchPlanError(
            f"Anthropic API error {response.status_code}: {response.text[:500]}"
        )

    raw_text = _extract_text(response.json())
    if not raw_text:
        raise SearchPlanError("Claude returned an empty response.")

    try:
        parsed = _extract_json(raw_text)
    except Exception as exc:
        raise SearchPlanError(
            "Claude did not return valid JSON.", raw_response=raw_text
        ) from exc

    reasoning = str(parsed.get("reasoning", "")).strip()
    candidate_sql = str(parsed.get("sql_query", "")).strip()

    try:
        sql_query = _sanitize_sql(candidate_sql)
    except Exception as exc:
        raise SearchPlanError(
            str(exc),
            raw_response=raw_text,
            parsed_plan=parsed,
            reasoning=reasoning,
            candidate_sql=candidate_sql,
        ) from exc

    return SearchPlan(
        sql_query=sql_query,
        reasoning=reasoning,
        raw_response=raw_text,
        candidate_sql=candidate_sql,
        parsed_plan=parsed,
    )


def execute_sql_search(sql_query: str) -> list[dict[str, Any]]:
    """Execute sanitized SQL query and return results as list of dicts."""
    init_db()
    # Validate at sink as a defense-in-depth control before executing raw text.
    safe_sql = _sanitize_sql(sql_query)
    with get_session() as session:
        try:
            result = session.execute(text(safe_sql))
            return [dict(row) for row in result.mappings().all()]
        except SQLAlchemyError as exc:
            raise ValueError(f"Generated SQL failed to execute: {exc}") from exc


def keyword_game_search(query: str, limit: int = 200) -> pd.DataFrame:
    """Full-text search across usernames, openings, and game metadata."""
    init_db()
    q = query.strip()
    if not q:
        return pd.DataFrame()

    like = f"%{q}%"
    with get_session() as session:
        rows = (
            session.query(Game, GameParticipant, Player, GameAnalysis.summary_cp)
            .join(GameParticipant, GameParticipant.game_id == Game.id)
            .join(Player, Player.id == GameParticipant.player_id)
            .outerjoin(GameAnalysis, GameAnalysis.game_id == Game.id)
            .filter(
                or_(
                    Player.username.ilike(like),
                    GameParticipant.opponent_username.ilike(like),
                    GameParticipant.result.ilike(like),
                    GameParticipant.color.ilike(like),
                    Game.time_control.ilike(like),
                    Game.eco_code.ilike(like),
                    Game.opening_name.ilike(like),
                    Game.lichess_opening.ilike(like),
                    Game.white_username.ilike(like),
                    Game.black_username.ilike(like),
                    Game.pgn.ilike(like),
                )
            )
            .order_by(Game.played_at.desc())
            .limit(limit)
            .all()
        )

    data = [
        {
            "game_id": game.id,
            "played_at": game.played_at,
            "player": player.username,
            "opponent": participant.opponent_username,
            "color": participant.color,
            "result": participant.result,
            "time_control": game.time_control,
            "opening": game.opening_name,
            "lichess_opening": game.lichess_opening,
            "opening_label": opening_display_label(
                game.eco_code,
                game.lichess_opening,
                game.opening_name,
                game.pgn,
            ),
            "pgn": game.pgn,
            "stockfish_cp": int(summary_cp or 0),
        }
        for game, participant, player, summary_cp in rows
    ]
    return pd.DataFrame(data)


def recent_games_for_player(player: str, limit: int = 200) -> pd.DataFrame:
    """Fetch recent games for a player with evaluation data."""
    filters = HistoryFilters(player=player, lookback_days=3650, recent_limit=limit)
    service = HistoryService()
    return service.get_recent_games_with_eval(filters)
