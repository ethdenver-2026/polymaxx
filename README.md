# Signal Market

Prediction market signal producer and consumer system. The producer generates trading signals from weather forecast data (NOAA/Open-Meteo ensembles) and broadcasts them over WebSocket. Consumers subscribe to signals, evaluate them, and execute trades on Polymarket.

## Judges

Kite AI: [x402 code](https://github.com/ethdenver-2026/polymaxx/blob/180f3f380eac84756ce55265b6f2c82a7ceb48a0/consumer/signal_consumer/payment.py#L50https://github.com/ethdenver-2026/polymaxx/blob/180f3f380eac84756ce55265b6f2c82a7ceb48a0/consumer/signal_consumer/payment.py#L50) used for paying for signals and managing producer and consumer reputations though x402

0g: [LLM](https://github.com/ethdenver-2026/polymaxx/blob/180f3f380eac84756ce55265b6f2c82a7ceb48a0/consumer/signal_consumer/llm_clients.py#L99) dynamtic pricing for bids

Fuuuuterllama: [AI driven websocket substrate ingestion](https://github.com/ethdenver-2026/polymaxx/blob/180f3f380eac84756ce55265b6f2c82a7ceb48a0/consumer/signal_consumer/ws_ingestion.py#L1)
## Prerequisites

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Node.js 18+ (for dashboard)
- Docker & Docker Compose (for containerized deployment)

## Project Structure

```
producer/       # Signal producer (weather forecasts + Polymarket signals)
consumer/       # Signal consumer (subscribes to producer, executes trades)
dashboard/      # React dashboard for monitoring consumer state
shared/         # Shared signal schema (used by both producer and consumer)
signal.sh       # Local stack launcher (starts all services)
```

## Installing Dependencies

Each component has its own `pyproject.toml` and virtual environment managed by `uv`.

```bash
# Producer
cd producer
uv sync

# Consumer
cd consumer
uv sync

# Dashboard
cd dashboard
pnpm install
```

`uv sync` installs all core dependencies including TSA signal generation (numpy, pandas, xgboost) and trading (py-clob-client). Dev tools (pytest, ruff, mypy) are included automatically in development.

## Configuration

Copy `.env.example` to `.env` and fill in the required values:

```bash
cp .env.example .env
```

Key variables: `PRODUCER_PRIVATE_KEY`, `PRODUCER_WALLET_ADDRESS`, `PRODUCER_DID`, consumer credentials, and `ANTHROPIC_API_KEY`. See `.env.example` for the full list.

## Running Locally

### Producer

```bash
cd producer
uv run signal-producer producer --host 127.0.0.1 --port 8000
```

Or using the module directly:

```bash
cd producer
uv run python -m signal_producer --producer --host 127.0.0.1 --port 8000
```

The producer starts a WebSocket server and continuously generates signals from weather forecast data.

### Consumer

```bash
cd consumer
uv run signal-consumer --host 127.0.0.1 --api-port 8766 --verbose
```

Or using the module directly:

```bash
cd consumer
uv run python -m signal_consumer --host 127.0.0.1 --api-port 8766 --verbose
```

The consumer connects to the producer's WebSocket, evaluates signals, and serves a REST API for the dashboard.

### Full Local Stack

The `signal.sh` script starts the producer, two consumers, and two dashboards:

```bash
# Start everything
./signal.sh start

# Stop everything
./signal.sh stop
```

Services started:
- Producer: http://127.0.0.1:8000
- Consumer A API: http://127.0.0.1:8766
- Consumer B API: http://127.0.0.1:8767
- Dashboard A: http://127.0.0.1:5173
- Dashboard B: http://127.0.0.1:5174

Logs are written to `tmp/local-stack-logs/`.

## Running with Docker

### Build Images

```bash
# Build all services
docker compose build

# Or build individually
docker compose build producer
docker compose build consumer-a
docker compose build dashboard-a
```

### Start Services

```bash
# Start the full stack
docker compose up

# Start in background
docker compose up -d

# View logs
docker compose logs -f producer
docker compose logs -f consumer-a
```

### Stop Services

```bash
docker compose down
```

Docker Compose starts the same services as the local stack: producer, two consumers, and two dashboards. Environment variables are loaded from `.env`.

## Running Tests

```bash
# Producer tests
cd producer
uv run pytest tests/ -v

# Consumer tests
cd consumer
uv run pytest tests/ -v
```

## CLI Tools

The producer CLI has additional commands for market inspection:

```bash
cd producer

# Check a specific market
uv run signal-producer check nyc

# Scan for new city markets
uv run signal-producer scan-cities

# Check resolution outcomes
uv run signal-producer outcomes 2026-02-20

# Collect forecasts for backtesting
uv run signal-producer collect --max-days 4
```
