FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY dispatchers ./dispatchers
COPY start_workers.py ./

RUN pip install --no-cache-dir .

CMD ["python", "start_workers.py"]
