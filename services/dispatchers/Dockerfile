FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY dispatchers ./dispatchers
COPY start_workers.py ./

RUN pip install --no-cache-dir .

CMD ["python", "start_workers.py"]
