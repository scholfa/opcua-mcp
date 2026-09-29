# syntax=docker/dockerfile:1

# --- Build stage: install locked dependencies into /app/.venv ---
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# --- Runtime stage ---
FROM python:3.13-slim-bookworm
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app main.py config.py security.py ./
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/
# Client certificate location; mount a volume here to keep a generated certificate
RUN mkdir /app/certs && chown app:app /app/certs

# Credentials are never baked into the image: pass them at runtime,
# e.g. docker run --env-file .env ...
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=stdio \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    MCP_ALLOWED_HOSTS=localhost:*,127.0.0.1:*

# The entrypoint starts as root only to make a mounted /app/certs writable, then drops to
# the unprivileged app user before starting the server
EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
