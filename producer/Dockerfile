FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY shared /app/shared
COPY producer /app/producer

WORKDIR /app/producer
RUN mkdir -p /app/producer/data
RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "python", "-m", "signal_producer", "--producer", "--host", "0.0.0.0", "--port", "8000"]
