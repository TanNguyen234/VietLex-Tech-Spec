# Use a lightweight python base image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    CONTENT_STORE_PATH=/data/content_store.sqlite3 \
    LEGAL_FTS_PATH=/data/legal_fts.sqlite3

# Set working directory
WORKDIR /app

# Install system dependencies if required
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY app/ ./app/
COPY assets/ ./assets/
COPY guardrails_config/ ./guardrails_config/
COPY docs/evaluation/runs/answer-v3-golden50-expanded14962-rrf-dbsf-20260903/manifest.json docs/evaluation/runs/answer-v3-golden50-expanded14962-rrf-dbsf-20260903/answer_results.json ./docs/evaluation/runs/answer-v3-golden50-expanded14962-rrf-dbsf-20260903/

# The indexed corpus is mounted at runtime and is never baked into the image.
VOLUME ["/data"]

# Expose server port
EXPOSE 8000

# Start FastAPI application using uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
