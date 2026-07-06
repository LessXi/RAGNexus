FROM python:3.11-slim
WORKDIR /app

# Install uv via pip (no ghcr dependency)
RUN pip install uv --no-cache-dir

# Copy dependency metadata first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project --frozen

# Copy source
COPY . .

# Install the project package
RUN uv pip install --python .venv/bin/python -e . --no-deps
ENV PYTHONPATH=/app/src

EXPOSE 8000
CMD [".venv/bin/python", "-m", "uvicorn", "ragnexus.composition:build_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
