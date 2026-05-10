![Wood League Chess Logo](wood_league_chess_logo.svg)

# Wood League Chess
Wood League Chess is a chess analysis website built for chess clubs. It was born out of out chess club's (the Wood League Creatures) desire to have more, different, and unique visualizations and analysis of our play. 

> Wood League Creatures: Drink the Mercury!

## Guiding Principles

The guiding principles of this project are:

1. Provide new and fresh insights into our games.
2. Don't reinvent chess.com or lichess analysis! make something new.
3. Provide club-centric views of our gameplay data. Where possible allow for filtering, skimming, and scanning games for player pattern, and club patterns. 
4. Finding and sharing games should be fast and easy - think simple URLs, plain language searches. 
5. The design should be functional and unique, charts, graphs, and graphics should be striking and informative. (See design principles below).
6. This is not a place to play chess. 
7. This is not a walled garden - it should be easy to liberate your data to other formats. 

## Guiding Design Aesthetic 

We want this site to make our chess data beautiful. The guiding aesthetic is nineteenth century data visualizations in general, and the absolutely stellar (and groundbreaking) work of [W.E.B. Du Bois 1900 Paris Exposition](https://www.smithsonianmag.com/history/first-time-together-and-color-book-displays-web-du-bois-visionary-infographics-180970826/) specifically. 

***{insert color pallet here}***

## Implementation

Practically speaking this project looks like:

* **Data layer.** A database of games ingested from wherever they are played (e.g. chess.com)
* **User layer.** A website for building and presenting the visualizations, searching games, and using the service.
* **Worker layer.** A worker layer for running in depth analysis of the games (e.g. stockfish, lc0)

## Architecture

This project is implemented as a mono-repo decided into the following services:

* A Django App 
  * Hosts the website
  * Hosts the analysis work API
* PostgreSQL Database
* Analysis Workers 
  * Stockfish workers (local / cloud)
  * Lc0 workers (local / cloud)

## Our Service Implementation

We run the website on Railway (Django App, Dispatcher for ingest marshaling Runpods, PostgresSQL), and Runpod (stockfish, lc0 workers).

| Service                     | Description                    | Deployment |
| --------------------------- | ------------------------------ | ---------- |
| `services/app`              | Django web application         | Railway    |
| `services/dispatchers`      | RunPod job dispatcher          | Railway    |
| `services/stockfish_worker` | Stockfish analysis worker      | RunPod     |
| `services/lc0_worker`       | Lc0 neural net analysis worker | RunPod     |



## Local Development

Install uv if needed:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Install all workspace members:
```bash
uv sync
```

### Running services locally

Each service runs independently. Open a terminal for each.

**Django app** (`services/app`)
```bash
cd services/app
cp .env.example .env          # configure DATABASE_URL and other vars

# run from withing the `services/app` directory
uv run python manage.py runserver
```
App is available at `http://localhost:8000`.

**Dispatcher** (`services/dispatchers`)

Requires a running Django app and valid RunPod credentials.
```bash
cd services/dispatchers
cp .env.example .env          # configure DATABASE_URL, WORKER_API_URL, RUNPOD_* vars
python start_workers.py
```

**Stockfish worker** (`services/stockfish_worker`)

Simulates a RunPod worker locally using a `test_input.json` file.
```bash
cd services/stockfish_worker
pip install -r requirements.txt
export WORKER_API_URL="http://localhost:8000"
export WORKER_API_KEY="your-worker-api-key"
export STOCKFISH_PATH="/usr/local/bin/stockfish"   # path to local stockfish binary
python handler.py
```

**Lc0 worker** (`services/lc0_worker`)

Simulates a RunPod worker locally using a `test_input.json` file.
```bash
cd services/lc0_worker
pip install -e .
export WORKER_API_URL="http://localhost:8000"
export WORKER_API_KEY="your-worker-api-key"
export LC0_PATH="/usr/local/bin/lc0"
python handler.py
```
