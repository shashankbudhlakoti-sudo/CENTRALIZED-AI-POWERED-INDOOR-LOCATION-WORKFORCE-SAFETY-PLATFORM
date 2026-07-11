FROM python:3.11-slim AS builder

# insightface has no Linux wheel pinned in this project (only the Windows
# one used for local dev) - on Linux it builds from source, which needs a
# C compiler, cmake, and OpenCV's runtime headers. Prophet needs the same
# compiler tools to build its cmdstan backend below.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-docker.txt requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt

# Prophet's Python package alone isn't enough - it needs the actual Stan
# compiler toolchain (cmdstan) installed separately. This is a genuine,
# well-known gotcha: pip installing 'prophet' does NOT build this for you.
# Runs here (in the builder, which has build-essential) and gets copied
# into the runtime stage below, so the final image doesn't need a compiler.
RUN python -m cmdstanpy.install_cmdstan --dir /opt/cmdstan --cores 4

# install_cmdstan creates a version-numbered subfolder (e.g.
# cmdstan-2.39.0), not /opt/cmdstan itself - cmdstanpy needs the exact
# versioned path, not the parent. A symlink means we never have to hardcode
# (and re-break on) the version number when cmdstanpy updates later.
RUN ln -s "/opt/cmdstan/$(ls /opt/cmdstan)" /opt/cmdstan/current
ENV CMDSTAN=/opt/cmdstan/current


FROM python:3.11-slim AS runtime

# opencv-python-headless still needs these two shared libraries at runtime
# even though it's the "headless" build - without them it fails to import.
# build-essential is here too because Prophet compiles its own specific
# Stan model on first use (not just at cmdstan install time) - this is a
# real trade-off (a compiler in the deployed image isn't ideal hardening
# posture) but is the pragmatic fix for a pilot; worth revisiting in
# Phase 8 by precompiling the model at build time instead and stripping
# this out.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements-docker.txt requirements.txt
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Prophet ships its own bundled cmdstan copy inside its package folder and
# tries to use that FIRST, ignoring the CMDSTAN env var entirely. That
# bundled copy is missing its makefile (a known prophet/cmdstanpy version
# mismatch - see facebook/prophet#1919), which fails a stricter validation
# check even though the binary itself may be fine. Removing it forces
# Prophet to fall back to the system-wide /opt/cmdstan/current we built
# properly above, with a real, complete installation.
RUN rm -rf /usr/local/lib/python3.11/site-packages/prophet/stan_model/cmdstan-*

# Carry the compiled cmdstan toolchain into the final image - this is
# what Prophet actually calls at runtime to fit models. Copies the
# symlink too, so this stage points at the same versioned folder without
# needing to know the version number itself.
COPY --from=builder /opt/cmdstan /opt/cmdstan
ENV CMDSTAN=/opt/cmdstan/current

COPY app ./app

USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import httpx; httpx.get('http://localhost:8001/health').raise_for_status()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
