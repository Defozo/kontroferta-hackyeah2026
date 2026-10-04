FROM node:24.13.0-bookworm-slim@sha256:4660b1ca8b28d6d1906fd644abe34b2ed81d15434d26d845ef0aced307cf4b6f AS web
WORKDIR /web
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web/ ./
COPY packages/contracts /packages/contracts
RUN npm run contracts:generate && npm run build

FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev make curl tesseract-ocr tesseract-ocr-pol tesseract-ocr-eng fonts-dejavu-core libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 && rm -rf /var/lib/apt/lists/*
# Build a fixed SQLite version instead of relying on the Python image version.
RUN curl -fsSL https://www.sqlite.org/2026/sqlite-autoconf-3510300.tar.gz -o /tmp/sqlite.tar.gz && tar -xzf /tmp/sqlite.tar.gz -C /tmp && cd /tmp/sqlite-autoconf-3510300 && ./configure --prefix=/usr/local --disable-readline && make -j2 && make install && ldconfig && rm -rf /tmp/sqlite*
ENV LD_LIBRARY_PATH=/usr/local/lib
RUN python -c "import sqlite3; assert tuple(map(int, sqlite3.sqlite_version.split('.'))) >= (3,51,3), sqlite3.sqlite_version"
RUN pip install --no-cache-dir uv==0.6.14
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH=/app/.venv/bin:$PATH PLAYWRIGHT_BROWSERS_PATH=/opt/browsers PYTHONUNBUFFERED=1
RUN python -m playwright install chromium && chmod -R a+rX /opt/browsers
RUN python -m playwright install-deps chromium && rm -rf /var/lib/apt/lists/*
COPY apps/api apps/api
COPY apps/worker apps/worker
COPY apps/__init__.py apps/__init__.py
COPY packages packages
COPY fixtures/demo fixtures/demo
COPY scripts scripts
COPY migrations migrations
COPY alembic.ini .
COPY --from=web /web/dist apps/web/dist
RUN useradd -m -u 10001 kontroferta && mkdir /data && chown -R kontroferta:kontroferta /data /app
USER kontroferta
ENV DATABASE_URL=sqlite:////data/kontroferta.db FILE_STORAGE_PATH=/data/files
EXPOSE 8080
CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn apps.api.main:app --no-access-log --host 0.0.0.0 --port 8080"]
