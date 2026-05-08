# services/stockfish_worker/Dockerfile
# Build from REPO ROOT: docker build -f services/stockfish_worker/Dockerfile .

FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends wget tar \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q "https://github.com/official-stockfish/Stockfish/releases/download/sf_18/stockfish-ubuntu-x86-64-avx2.tar" \
        -O /tmp/stockfish.tar \
    && tar -xf /tmp/stockfish.tar -C /tmp \
    && find /tmp -name "stockfish*" -type f -perm /111 | head -1 \
         | xargs -I{} mv {} /usr/games/stockfish \
    && chmod +x /usr/games/stockfish \
    && rm -f /tmp/stockfish.tar

ENV STOCKFISH_PATH=/usr/games/stockfish \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy shared package first (better layer caching — changes less often)
COPY packages/shared ./packages/shared

# Copy service code
COPY services/stockfish_worker/pyproject.toml .
COPY services/stockfish_worker/handler.py .
COPY services/stockfish_worker/stockfish_pipeline ./stockfish_pipeline

# Use pip (not uv) so [tool.uv.sources] workspace refs are ignored
RUN pip install --no-cache-dir packages/shared && \
    pip install --no-cache-dir .

CMD ["python", "handler.py"]
