# Stage 1: build the React dashboard
FROM node:22-slim AS dashboard
WORKDIR /src/dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard/ ./
# vite writes to ../engine/src/yesrule/web/dist
RUN mkdir -p ../engine/src/yesrule/web && npx vite build

# Stage 2: the engine, serving the built dashboard
FROM python:3.13-slim
RUN pip install --no-cache-dir uv==0.12.19
WORKDIR /app
COPY engine/pyproject.toml engine/uv.lock engine/README.md* ./
COPY engine/src ./src
COPY --from=dashboard /src/engine/src/yesrule/web/dist ./src/yesrule/web/dist
RUN uv sync --frozen --no-dev
RUN useradd --system --uid 10001 yesrule && mkdir /data && chown yesrule /data
USER yesrule
ENV YESRULE_DATABASE_URL=sqlite:////data/yesrule.db PATH="/app/.venv/bin:$PATH"
VOLUME /data
EXPOSE 8787
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8787/health')"
CMD ["yesrule", "serve", "--host", "0.0.0.0", "--port", "8787"]
