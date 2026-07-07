FROM python:3.11-slim AS builder

# insightface has no Linux wheel pinned in this project (only the Windows
# one used for local dev) - on Linux it builds from source, which needs a
# C compiler, cmake, and OpenCV's runtime headers.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-docker.txt requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


FROM python:3.11-slim AS runtime

# opencv-python-headless still needs these two shared libraries at runtime
# even though it's the "headless" build - without them it fails to import.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements-docker.txt requirements.txt
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY app ./app

USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import httpx; httpx.get('http://localhost:8001/health').raise_for_status()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
