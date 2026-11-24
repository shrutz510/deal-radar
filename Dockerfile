# Deal Radar: standard library only, so the image is just Python plus the source.
FROM python:3.12-slim

RUN useradd --create-home --uid 10001 app && mkdir /data && chown app /data
WORKDIR /app
COPY src/ src/

USER app
ENV DEAL_RADAR_HOST=0.0.0.0 \
    DEAL_RADAR_PORT=8787 \
    DEAL_RADAR_DB=/data/deals.db \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['DEAL_RADAR_PORT'] + '/api/state', timeout=4)"]

CMD ["python", "src/server.py", "--no-browser"]
