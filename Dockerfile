FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/models

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Download the embedding and reranking models while building the image, so a cold start on
# Cloud Run doesn't spend 30 seconds fetching them.
RUN python -c "from fastembed import TextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; \
TextEmbedding('snowflake/snowflake-arctic-embed-xs'); TextCrossEncoder('Xenova/ms-marco-MiniLM-L-6-v2')"

COPY fedsight ./fedsight
COPY web ./web
COPY data ./data
COPY evals/results ./evals/results

# Cloud Run sets $PORT; default to 8080 for local docker runs.
CMD ["sh", "-c", "uvicorn fedsight.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
