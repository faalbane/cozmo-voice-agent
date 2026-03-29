FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/
COPY scripts/ scripts/
COPY public/ public/

ENV PYTHONUNBUFFERED=1

# Default: run in server mode (handles multiple concurrent calls)
CMD ["python", "src/main.py", "--mode", "server", "--port", "8080"]
