FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md main.py ./
COPY monster_siren ./monster_siren

RUN python -m pip install .

VOLUME ["/downloads"]

ENTRYPOINT ["msr-dl"]
CMD ["download", "--output", "/downloads"]
