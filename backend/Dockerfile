# =============================================================================
# Backend image — FastAPI + SQLAlchemy 2 + Alembic
# =============================================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Set to "true" to include dev tooling (ruff, mypy, pytest) in the image, which
# is what lets `docker compose run api pytest` work without a host Python.
ARG INSTALL_DEV=false

COPY pyproject.toml ./
COPY alembic.ini ./
COPY app ./app
COPY alembic ./alembic
COPY tests ./tests

RUN python -m pip install --upgrade pip \
    && if [ "$INSTALL_DEV" = "true" ]; then \
    python -m pip install -e ".[dev]"; \
    else \
    python -m pip install .; \
    fi

# Run as a non-root user. The storage directories are created here so the
# container still starts when no bind mount is supplied.
RUN groupadd --system appuser \
    && useradd --system --gid appuser --home-dir /app appuser \
    && mkdir -p /storage/raw /storage/processed /storage/rejected \
    && chown -R appuser:appuser /app /storage
USER appuser

EXPOSE 8000

# Liveness only — it must not depend on PostgreSQL, or a database outage would
# make Docker kill an otherwise healthy container.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
