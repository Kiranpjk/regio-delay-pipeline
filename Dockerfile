FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install . && useradd --create-home --uid 10001 app && mkdir /data && chown app /data
COPY fixtures ./fixtures

USER app
VOLUME ["/data"]
ENTRYPOINT ["regio-delays", "--db", "/data/regio.duckdb"]
CMD ["--help"]
