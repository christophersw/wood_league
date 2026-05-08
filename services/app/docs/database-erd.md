# Database ERD

This document summarizes the current application database schema as defined in:

- `app/storage/models.py`
- `app/storage/database.py`

It includes:

- A full ERD for the current schema
- A simplified ERD focused on the tables the app actively uses most
- A data-flow diagram for ingest, queueing, engine analysis, and UI consumption

## Reading Notes

- `games` is the central table. It is game-centric: it has one row per unique game regardless of how many tracked players participated.
- `game_participants` is the normalized player-centric relationship. Use it for all per-player analytics. Has a unique constraint on `(game_id, player_id)`.
- Stockfish and Lc0 analyses are stored in parallel table families.
- `worker_heartbeats` is related to `analysis_jobs` only logically by `worker_id`; there is no foreign key.
- `users` and `opening_book` are standalone support tables and intentionally do not join into the gameplay graph.

## Full ERD

```mermaid
erDiagram
    players {
        int id PK
        string username UK "Chess.com username; unique + indexed"
        string display_name
    }

    users {
        int id PK
        string email UK "Application login; unique + indexed"
        string password_hash
        string role "default: member"
        boolean is_active "default: true"
        datetime created_at "default: utcnow"
    }

    games {
        string id PK "Game UUID from Chess.com; String(64)"
        datetime played_at "indexed"
        string time_control
        string white_username "nullable"
        string black_username "nullable"
        int white_rating "nullable"
        int black_rating "nullable"
        string result_pgn "1-0 / 0-1 / 1/2-1/2; nullable"
        string winner_username "NULL for draws; nullable"
        string eco_code "default: empty string"
        string opening_name "default: empty string"
        string lichess_opening "nullable"
        text pgn "default: empty string"
    }

    game_participants {
        int id PK
        string game_id FK "indexed; unique with player_id"
        int player_id FK "indexed; unique with game_id"
        string color "White or Black"
        string opponent_username
        int player_rating "nullable"
        int opponent_rating "nullable"
        string result "Win / Loss / Draw"
        float quality_score "Stockfish accuracy 0-100; nullable"
        int blunder_count "nullable"
        int mistake_count "nullable"
        int inaccuracy_count "nullable"
        float acpl "Average centipawn loss; nullable"
    }

    game_analysis {
        int id PK
        string game_id FK "unique + indexed"
        datetime analyzed_at "nullable"
        int engine_depth "nullable"
        float summary_cp "White-relative centipawn eval; default: 0.0"
        float white_accuracy "nullable"
        float black_accuracy "nullable"
        float white_acpl "nullable"
        float black_acpl "nullable"
        int white_blunders "nullable"
        int white_mistakes "nullable"
        int white_inaccuracies "nullable"
        int black_blunders "nullable"
        int black_mistakes "nullable"
        int black_inaccuracies "nullable"
    }

    move_analysis {
        int id PK
        int analysis_id FK "indexed"
        int ply
        string san
        text fen
        float cp_eval "White-relative centipawn eval"
        float cpl "Centipawn loss for the mover; nullable"
        string best_move "default: empty string"
        string arrow_uci "default: empty string"
        string classification "Brilliant/Great/Best/Excellent/Inaccuracy/Mistake/Blunder; nullable"
    }

    lc0_game_analysis {
        int id PK
        string game_id FK "unique + indexed"
        datetime analyzed_at "nullable"
        int engine_nodes "MCTS node budget; nullable"
        string network_name "Lc0 weights file; nullable"
        float white_win_prob "nullable"
        float white_draw_prob "nullable"
        float white_loss_prob "nullable"
        float black_win_prob "nullable"
        float black_draw_prob "nullable"
        float black_loss_prob "nullable"
        int white_blunders "nullable"
        int white_mistakes "nullable"
        int white_inaccuracies "nullable"
        int black_blunders "nullable"
        int black_mistakes "nullable"
        int black_inaccuracies "nullable"
    }

    lc0_move_analysis {
        int id PK
        int analysis_id FK "indexed"
        int ply
        string san
        text fen
        int wdl_win "White win permille (sums to 1000); nullable"
        int wdl_draw "nullable"
        int wdl_loss "nullable"
        float cp_equiv "Q-derived centipawn equivalent; nullable"
        string best_move "default: empty string"
        string arrow_uci "default: empty string"
        float move_win_delta "Win% drop for the mover; nullable"
        string classification "nullable"
    }

    analysis_jobs {
        int id PK
        string game_id FK "indexed"
        string status "pending/running/completed/failed; default: pending; indexed"
        int priority "default: 0"
        string engine "stockfish/lc0; default: stockfish; indexed"
        int depth "Stockfish depth or Lc0 node budget; default: 20"
        datetime created_at "default: utcnow"
        datetime started_at "nullable"
        datetime completed_at "nullable"
        string worker_id "Logical link to worker_heartbeats.worker_id; nullable"
        text error_message "nullable"
        int retry_count "default: 0"
    }

    worker_heartbeats {
        string worker_id PK "String(64)"
        datetime last_seen "default: utcnow"
        string status "starting/analyzing/idle/error/stopped; default: idle"
        string current_game_id "Informational only; nullable"
        int jobs_completed "default: 0"
        int jobs_failed "default: 0"
        datetime started_at "default: utcnow"
    }

    opening_book {
        int id PK
        string eco "indexed"
        string name "indexed"
        text pgn "Moves reaching this position"
        string epd UK "EPD string lookup key; unique + indexed"
    }

    players ||--o{ game_participants : "tracked player"
    games ||--o{ game_participants : "player/game slice"

    games ||--o| game_analysis : "Stockfish summary"
    game_analysis ||--o{ move_analysis : "per-ply Stockfish evals"

    games ||--o| lc0_game_analysis : "Lc0 summary"
    lc0_game_analysis ||--o{ lc0_move_analysis : "per-ply WDL evals"

    games ||--o{ analysis_jobs : "analysis queue / run history"
```

## Simplified ERD

This view hides support tables and low-traffic columns so the core application model is easier to inspect.

```mermaid
erDiagram
    players {
        int id PK
        string username UK
        string display_name
    }

    games {
        string id PK
        datetime played_at
        string white_username
        string black_username
        string result_pgn
        string eco_code
        string opening_name
        string lichess_opening
        text pgn
    }

    game_participants {
        int id PK
        string game_id FK
        int player_id FK
        string color
        string opponent_username
        string result
        float quality_score
        float acpl
    }

    game_analysis {
        int id PK
        string game_id FK
        int engine_depth
        float summary_cp
        float white_accuracy
        float black_accuracy
        float white_acpl
        float black_acpl
    }

    move_analysis {
        int id PK
        int analysis_id FK
        int ply
        string san
        float cp_eval
        float cpl
        string best_move
        string classification
    }

    lc0_game_analysis {
        int id PK
        string game_id FK
        int engine_nodes
        string network_name
        float white_win_prob
        float white_draw_prob
        float white_loss_prob
        float black_win_prob
        float black_draw_prob
        float black_loss_prob
    }

    lc0_move_analysis {
        int id PK
        int analysis_id FK
        int ply
        string san
        int wdl_win
        int wdl_draw
        int wdl_loss
        float cp_equiv
        string best_move
        float move_win_delta
        string classification
    }

    analysis_jobs {
        int id PK
        string game_id FK
        string engine
        string status
        int depth
        datetime created_at
    }

    players ||--o{ game_participants : "tracked player"
    games ||--o{ game_participants : "player/game slice"

    games ||--o| game_analysis : "Stockfish summary"
    game_analysis ||--o{ move_analysis : "Stockfish positions"

    games ||--o| lc0_game_analysis : "Lc0 summary"
    lc0_game_analysis ||--o{ lc0_move_analysis : "Lc0 positions"

    games ||--o{ analysis_jobs : "queue entries"
```

## Table Roles

### Core chess data

- `players`: tracked club/player identities from Chess.com.
- `games`: canonical game record with PGN, opening metadata, usernames, and timestamps. Game-centric — one row per unique game.
- `game_participants`: normalized per-player view of a game. One row per (tracked player × game), enforced by a unique constraint on `(game_id, player_id)`. Best source for all player-centric analytics.

### Stockfish analysis

- `game_analysis`: one Stockfish summary row per game. Includes per-side accuracy, ACPL, and move classification counts.
- `move_analysis`: one row per analyzed ply with centipawn eval, best move, CPL, and classification.

### Lc0 analysis

- `lc0_game_analysis`: one Lc0 WDL summary row per game. Includes per-side win/draw/loss probabilities and move classification counts.
- `lc0_move_analysis`: per-ply WDL permille values (White perspective), Q-derived centipawn equivalent, win-delta, best move, and classification.

### Queue and workers

- `analysis_jobs`: queue and execution history for both Stockfish and Lc0. `engine` column discriminates between them; `depth` is dual-purpose (Stockfish search depth or Lc0 node budget).
- `worker_heartbeats`: live worker status tracking; related to jobs by `worker_id` string, not FK.

### Support tables

- `users`: application authentication and authorization.
- `opening_book`: reference dataset for mapping board EPD strings to named openings. Loaded into a process-level LRU cache for fast lookup.

## Data Flow

```mermaid
flowchart TD
    A[Chess.com API] --> B[run_sync / sync_service]
    B --> C[players]
    B --> D[games]
    B --> E[game_participants]

    D --> F[Opening metadata in games]
    D --> G[Queue UI in Game Analysis]

    G --> H[analysis_jobs]

    H --> I[Stockfish worker]
    H --> J[Lc0 worker]

    I --> K[game_analysis]
    I --> L[move_analysis]

    J --> M[lc0_game_analysis]
    J --> N[lc0_move_analysis]

    I --> O[worker_heartbeats]
    J --> O

    P[opening_book] --> Q[opening lookup / enrichment]
    Q --> D

    D --> R[Opening Analysis page]
    E --> R
    K --> S[Game Analysis page]
    L --> S
    M --> S
    N --> S
    D --> T[Game Search page]
    E --> T
```

## Implementation Notes

- `games` has no foreign key to `players` — it is game-centric with usernames stored as plain strings. The player graph is connected entirely through `game_participants`.
- `game_participants` has a unique constraint on `(game_id, player_id)` named `uq_game_participant`.
- `game_participants.result` is always from the tracked player's perspective ('Win'/'Loss'/'Draw').
- `analysis_jobs.depth` is dual-purpose: Stockfish search depth for Stockfish jobs; MCTS node budget for Lc0 jobs.
- `worker_heartbeats.current_game_id` is informational only; it is not enforced by a foreign key.
- `opening_book` is a reference/lookup table and does not own any downstream records. It is populated once from Lichess TSV data files.
- All WDL values in `lc0_move_analysis` are stored from White's perspective regardless of who moved.
- `lc0_move_analysis` includes `arrow_uci` (best move arrow) matching the Stockfish `move_analysis` schema.
