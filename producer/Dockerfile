FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy dependency metadata first (changes rarely) so Docker caches the install layer
COPY shared /app/shared
COPY producer/pyproject.toml producer/uv.lock /app/producer/

# Install dependencies (cached unless pyproject.toml or uv.lock change)
WORKDIR /app/producer
RUN mkdir -p /app/producer/data
RUN uv sync --frozen --no-dev --no-install-project

# Now copy source code (changes often) and install the project itself
COPY producer /app/producer
COPY --from=tsa . /app/tsa-market-manipulation
RUN uv sync --frozen --no-dev

ENV TSA_PROJECT_PATH=/app/tsa-market-manipulation

EXPOSE 8000

CMD ["uv", "run", "python", "-m", "signal_producer", "--producer", "--host", "0.0.0.0", "--port", "8000"]
