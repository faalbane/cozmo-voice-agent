FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/
COPY scripts/ scripts/

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "src/main.py"]
CMD ["start"]
