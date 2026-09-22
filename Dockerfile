FROM python:3.13-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /uvx /bin/

LABEL org.opencontainers.image.source="https://github.com/kelvinhenriqu/Sankhya_ProposalCreation" \
      org.opencontainers.image.title="Sankhya Proposal Creation" \
      org.opencontainers.image.description="FastAPI para consulta Sankhya e geração de propostas PDF com LibreOffice headless" \
      org.opencontainers.image.version="0.1.14"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp \
    TMPDIR=/tmp \
    XDG_CACHE_HOME=/tmp/.cache

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        fontconfig \
        fonts-dejavu-core \
        fonts-liberation \
        libreoffice-core \
        libreoffice-writer \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --locked --no-dev --no-install-project \
    && mkdir -p /tmp/.cache /app/Templates \
    && chown -R appuser:appuser /app /tmp/.cache

COPY --chown=appuser:appuser app ./app

USER appuser

ENV PDF_CONVERTER=libreoffice \
    LIBREOFFICE_EXECUTABLE=/usr/bin/libreoffice \
    TEMPLATES_DIR=/app/Templates \
    PDF_CONVERSION_TIMEOUT=120 \
    PATH=/app/.venv/bin:$PATH

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
