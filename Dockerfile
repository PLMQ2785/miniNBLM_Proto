FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.28 /uv /uvx /bin/

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --only-group api

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY docker/api-entrypoint.sh /usr/local/bin/api-entrypoint

EXPOSE 8080

CMD ["sh", "/usr/local/bin/api-entrypoint"]
