FROM python:3.11-alpine3.23

ARG APP_VERSION=0.1.0
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="Topic Radar" \
    org.opencontainers.image.description="Self-hosted YouTube growth research for small channels" \
    org.opencontainers.image.source="https://github.com/Vangardo/content_radar" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.version=$APP_VERSION \
    org.opencontainers.image.revision=$VCS_REF
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RADAR_MODE=server RADAR_DATA_DIR=/data RADAR_PORT=8877 RADAR_SERVER_CONFIG_FILE=/run/secrets/radar_server
WORKDIR /opt/radar
RUN apk upgrade --no-cache && apk add --no-cache sqlite-libs libstdc++ \
    && python -c "import sqlite3; assert sqlite3.sqlite_version_info >= (3,51,3), sqlite3.sqlite_version" \
    && addgroup -g 10001 radar && adduser -D -u 10001 -G radar radar \
    && mkdir /data && chown radar:radar /data
COPY requirements-server.lock ./
RUN pip install --no-cache-dir --only-binary=:all: -r requirements-server.lock
COPY app ./app
COPY youtube_niche ./youtube_niche
COPY migrations ./migrations
COPY LICENSE UPSTREAM.md ./
USER radar
EXPOSE 8877
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8877/healthz',timeout=4)"
CMD ["python", "-m", "app"]
