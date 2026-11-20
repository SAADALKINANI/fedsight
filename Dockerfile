FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/models

# Hugging Face Spaces runs containers as user 1000, so run as that user everywhere.
RUN useradd -m -u 1000 user && mkdir /models && chown user /models

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
USER user

# Download the embedding and reranking models while building the image, so a cold start
# doesn't spend 30 seconds fetching them.
RUN python -c "from fastembed import TextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; \
TextEmbedding('snowflake/snowflake-arctic-embed-xs'); TextCrossEncoder('Xenova/ms-marco-MiniLM-L-6-v2')"

COPY --chown=user fedsight ./fedsight
COPY --chown=user web ./web
COPY --chown=user data ./data
COPY --chown=user evals/results ./evals/results

# Cloud Run sets $PORT; Hugging Face is told to use 8080 in its README header.
CMD ["sh", "-c", "uvicorn fedsight.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
