FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev


FROM python:3.12-slim

LABEL io.modelcontextprotocol.server.name="io.github.ymuichiro/yahoo-shopping-mcp"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV YAHOO_SHOPPING_MCP_HOST=0.0.0.0
ENV YAHOO_SHOPPING_MCP_PORT=8000
ENV YAHOO_SHOPPING_MCP_DATA_DIR=/data
ENV PATH=/app/.venv/bin:$PATH

RUN groupadd --system app && useradd --system --gid app --create-home --home-dir /app app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY pyproject.toml README.md ./
COPY src ./src

RUN mkdir -p /data && chown -R app:app /app /data

USER app

EXPOSE 8000

CMD ["yahoo-shopping-mcp"]
