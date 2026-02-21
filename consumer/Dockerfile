FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY shared /app/shared
COPY consumer /app/consumer

WORKDIR /app/consumer
RUN mkdir -p /app/data
RUN uv sync --frozen --no-dev

EXPOSE 9866
EXPOSE 9867

CMD ["uv", "run", "python", "-m", "signal_consumer.run", "--host", "0.0.0.0", "--api-port", "9866", "--verbose"]
