# The RecallLens API and web client with their model dependencies, CPU only.
# Run it with its database through docker-compose.yml: `docker compose up --build`.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.20 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    HF_HOME=/models \
    TOKENIZERS_PARALLELISM=false \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# Dependencies first, so a change to the source does not reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project --group ml

COPY src ./src
RUN uv sync --locked --group ml

# Model weights (/models) and trace spans (.traces) are all the app writes besides the database.
RUN useradd --create-home app && mkdir -p /models .traces && chown app /models .traces
USER app

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=12 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/manifest.webmanifest')"]
CMD ["sh", "-c", "python -m recall_lens.db.migrate && exec uvicorn recall_lens.api:app --host 0.0.0.0 --port 8000"]
