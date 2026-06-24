FROM python:3.11-slim
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency metadata first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project --frozen

# Copy source and install package
COPY . .
RUN uv sync --no-dev --frozen

EXPOSE 8000
CMD ["uv", "run", "python", "-m", "uvicorn", "ragnexus.composition:build_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
