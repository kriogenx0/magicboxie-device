FROM python:3.11-slim-bookworm AS base

# mpv for playback, ffmpeg (ffprobe) for reading movie durations when scanning the library.
RUN apt-get update && apt-get install -y --no-install-recommends \
    mpv \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY magicbox_device ./magicbox_device
RUN pip install --no-cache-dir .

ENV MAGICBOX_MOVIES_DIR=/movies
ENV MAGICBOX_DEVICE_NAME=MagicBox
EXPOSE 8000

ENTRYPOINT ["magicbox-device"]

# `make test` / `docker build --target test`: runs the suite inside the same
# environment the app ships in, so `make` never depends on a local Python.
FROM base AS test
RUN pip install --no-cache-dir pytest
COPY tests ./tests
ENTRYPOINT []
CMD ["python", "-m", "pytest", "-v"]
