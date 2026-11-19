# OpenText QA tool dashboard (FastAPI + Playwright Chromium) for Cloud Run. Deploy with deploy/cloudrun/deploy.ps1.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Kolkata \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Dependencies come from pyproject.toml (the one list); this slow layer is rebuilt only when it changes.
COPY pyproject.toml .
# libatomic1: Playwright's bundled Node needs it before `--with-deps` can install Chromium's own libraries
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
 && python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/req.txt \
 && pip install -r /tmp/req.txt \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

# Run from source (not pip-installed): rules.yaml and templates are found relative to the code.
COPY engine/ engine/
COPY app/ app/
COPY report/ report/
COPY governance/ governance/

# Run as a non-root user
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8080
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
