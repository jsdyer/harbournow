FROM python:3.13-slim AS build
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
COPY scripts/ scripts/
COPY web/ web/
COPY config/ config/
COPY tool.json README.md ./
RUN python scripts/build.py

FROM python:3.13-slim
RUN groupadd --gid 10001 harbour && useradd --uid 10001 --gid harbour --no-create-home harbour && mkdir -p /data && chown harbour:harbour /data
WORKDIR /app
COPY --from=build /install /usr/local
COPY --from=build /app/dist dist/
COPY collector/ collector/
COPY config/ config/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BIND_HOST=0.0.0.0 PORT=8090 DATABASE_PATH=/data/harbournow.sqlite
USER 10001:10001
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/api/v1/health',timeout=3)" || exit 1
CMD ["python", "-m", "collector.app"]
