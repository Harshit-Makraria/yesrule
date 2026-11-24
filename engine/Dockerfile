FROM python:3.13-slim
RUN pip install --no-cache-dir uv==0.12.19
WORKDIR /app
COPY pyproject.toml uv.lock README.md* ./
COPY src ./src
RUN uv sync --frozen --no-dev
ENV YESRULE_DATABASE_URL=sqlite:////data/yesrule.db PATH="/app/.venv/bin:$PATH"
VOLUME /data
EXPOSE 8787
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8787/health')"
CMD ["yesrule", "serve", "--host", "0.0.0.0", "--port", "8787"]
