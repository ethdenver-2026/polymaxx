#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT_DIR/tmp/local-stack-logs"
mkdir -p "$LOG_DIR"

require_var() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "ERROR: required env var '$name' is missing or empty" >&2
    exit 1
  fi
}

ensure_port_free() {
  local port="$1"
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "ERROR: port $port is already in use" >&2
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >&2 || true
    exit 1
  fi
}

start_process() {
  local name="$1"
  local logfile="$2"
  local pidfile="$3"
  shift 3
  nohup "$@" >"$logfile" 2>&1 &
  local pid=$!
  echo "$pid" >"$pidfile"
  echo "$name started (pid=$pid, log=$logfile)"
}

stop_pidfile() {
  local name="$1"
  local pidfile="$2"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 0.3
      kill -9 "$pid" 2>/dev/null || true
      echo "$name stopped (pid=$pid)"
    else
      echo "$name not running (stale pidfile)"
    fi
    rm -f "$pidfile"
  else
    echo "$name pidfile not found"
  fi
}

stop_port_if_listening() {
  local name="$1"
  local port="$2"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    for pid in $pids; do
      kill "$pid" 2>/dev/null || true
      sleep 0.2
      kill -9 "$pid" 2>/dev/null || true
    done
    echo "$name stopped via port $port"
  fi
}

preflight_start() {
  if [[ ! -f "$ROOT_DIR/.env" ]]; then
    echo "ERROR: $ROOT_DIR/.env not found" >&2
    exit 1
  fi
  if [[ ! -f "$ROOT_DIR/dashboard/package.json" ]]; then
    echo "ERROR: dashboard dependencies not found (missing dashboard/package.json)" >&2
    exit 1
  fi

  set -a
  source "$ROOT_DIR/.env"
  set +a

  require_var PRODUCER_PRIVATE_KEY
  require_var PRODUCER_WALLET_ADDRESS
  require_var PRODUCER_DID
  require_var CONSUMER_A_DID
  require_var CONSUMER_A_PRIVATE_KEY
  require_var CONSUMER_A_PAYMENT_WALLET_ADDRESS
  require_var CONSUMER_A_PAYMENT_PRIVATE_KEY
  require_var CONSUMER_A_TRADING_WALLET_ADDRESS
  require_var CONSUMER_A_TRADING_PRIVATE_KEY
  require_var CONSUMER_B_DID
  require_var CONSUMER_B_PRIVATE_KEY
  require_var CONSUMER_B_PAYMENT_WALLET_ADDRESS
  require_var CONSUMER_B_PAYMENT_PRIVATE_KEY
  require_var CONSUMER_B_TRADING_WALLET_ADDRESS
  require_var CONSUMER_B_TRADING_PRIVATE_KEY
  require_var G0_API_KEY

  ensure_port_free 8000
  ensure_port_free 8766
  ensure_port_free 8767
  ensure_port_free 5173
  ensure_port_free 5174
}

start_stack() {
  preflight_start

  start_process \
    "producer" \
    "$LOG_DIR/producer.log" \
    "$LOG_DIR/producer.pid" \
    env \
      POLYMARKET_PRIVATE_KEY="$PRODUCER_PRIVATE_KEY" \
      POLYMARKET_WALLET_ADDRESS="$PRODUCER_WALLET_ADDRESS" \
      PRODUCER_DID="$PRODUCER_DID" \
      bash -lc "cd \"$ROOT_DIR/producer\" && set -a && source \"$ROOT_DIR/.env\" && set +a && uv run signal-producer producer --host 127.0.0.1 --port 8000"

  start_process \
    "consumer-a" \
    "$LOG_DIR/consumer-a.log" \
    "$LOG_DIR/consumer-a.pid" \
    env \
      CONSUMER_DID="$CONSUMER_A_DID" \
      CONSUMER_WALLET_ADDRESS="$CONSUMER_A_PAYMENT_WALLET_ADDRESS" \
      POLYMARKET_PRIVATE_KEY="$CONSUMER_A_PRIVATE_KEY" \
      TRADING_WALLET_ADDRESS="$CONSUMER_A_TRADING_WALLET_ADDRESS" \
      TRADING_WALLET_PRIVATE_KEY="$CONSUMER_A_TRADING_PRIVATE_KEY" \
      PAYMENT_WALLET_ADDRESS="$CONSUMER_A_PAYMENT_WALLET_ADDRESS" \
      PAYMENT_WALLET_PRIVATE_KEY="$CONSUMER_A_PAYMENT_PRIVATE_KEY" \
      PRODUCER_WS_URL="ws://127.0.0.1:8000/ws/signals" \
      PRODUCER_BID_WS_URL="ws://127.0.0.1:8000/ws/bids" \
      BID_LLM_PROVIDER="g0" \
      X402_MODE="x402_v2" \
      SIWX_CHALLENGE_URL="http://127.0.0.1:8000/x402/v2/siwx/challenge" \
      SIWX_AUTH_URL="http://127.0.0.1:8000/x402/v2/siwx/auth" \
      SIWX_APP_ID="signal-market-demo" \
      TRADING_MODE="${TRADING_MODE:-paper}" \
      bash -lc "cd \"$ROOT_DIR/consumer\" && set -a && source \"$ROOT_DIR/.env\" && set +a && uv run signal-consumer --host 127.0.0.1 --api-port 8766 --verbose"

  start_process \
    "consumer-b" \
    "$LOG_DIR/consumer-b.log" \
    "$LOG_DIR/consumer-b.pid" \
    env \
      CONSUMER_DID="$CONSUMER_B_DID" \
      CONSUMER_WALLET_ADDRESS="$CONSUMER_B_PAYMENT_WALLET_ADDRESS" \
      POLYMARKET_PRIVATE_KEY="$CONSUMER_B_PRIVATE_KEY" \
      TRADING_WALLET_ADDRESS="$CONSUMER_B_TRADING_WALLET_ADDRESS" \
      TRADING_WALLET_PRIVATE_KEY="$CONSUMER_B_TRADING_PRIVATE_KEY" \
      PAYMENT_WALLET_ADDRESS="$CONSUMER_B_PAYMENT_WALLET_ADDRESS" \
      PAYMENT_WALLET_PRIVATE_KEY="$CONSUMER_B_PAYMENT_PRIVATE_KEY" \
      PRODUCER_WS_URL="ws://127.0.0.1:8000/ws/signals" \
      PRODUCER_BID_WS_URL="ws://127.0.0.1:8000/ws/bids" \
      BID_LLM_PROVIDER="g0" \
      X402_MODE="x402_v2" \
      SIWX_CHALLENGE_URL="http://127.0.0.1:8000/x402/v2/siwx/challenge" \
      SIWX_AUTH_URL="http://127.0.0.1:8000/x402/v2/siwx/auth" \
      SIWX_APP_ID="signal-market-demo" \
      TRADING_MODE="${TRADING_MODE:-paper}" \
      bash -lc "cd \"$ROOT_DIR/consumer\" && set -a && source \"$ROOT_DIR/.env\" && set +a && uv run signal-consumer --host 127.0.0.1 --api-port 8767 --verbose"

  start_process \
    "dashboard-a" \
    "$LOG_DIR/dashboard-a.log" \
    "$LOG_DIR/dashboard-a.pid" \
    bash -lc "cd \"$ROOT_DIR/dashboard\" && API_TARGET=\"http://127.0.0.1:8766\" npm run dev -- --host 127.0.0.1 --port 5173 --strictPort"

  start_process \
    "dashboard-b" \
    "$LOG_DIR/dashboard-b.log" \
    "$LOG_DIR/dashboard-b.pid" \
    bash -lc "cd \"$ROOT_DIR/dashboard\" && API_TARGET=\"http://127.0.0.1:8767\" npm run dev -- --host 127.0.0.1 --port 5174 --strictPort"

  echo
  echo "Started local stack."
  echo "Dashboard A: http://127.0.0.1:5173"
  echo "Dashboard B: http://127.0.0.1:5174"
  echo "Producer:    http://127.0.0.1:8000/health"
  echo "Logs:        $LOG_DIR"
}

stop_stack() {
  stop_pidfile "dashboard-b" "$LOG_DIR/dashboard-b.pid"
  stop_pidfile "dashboard-a" "$LOG_DIR/dashboard-a.pid"
  stop_pidfile "consumer-b" "$LOG_DIR/consumer-b.pid"
  stop_pidfile "consumer-a" "$LOG_DIR/consumer-a.pid"
  stop_pidfile "producer" "$LOG_DIR/producer.pid"

  # Fallback by known ports for stale/orphaned processes.
  stop_port_if_listening "dashboard-a" 5173
  stop_port_if_listening "dashboard-b" 5174
  stop_port_if_listening "consumer-a" 8766
  stop_port_if_listening "consumer-b" 8767
  stop_port_if_listening "producer" 8000

  echo "Stop complete."
}

reset_db() {
  local active_ports=()
  local port
  for port in 8000 8766 8767 5173 5174; do
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      active_ports+=("$port")
    fi
  done

  if (( ${#active_ports[@]} > 0 )); then
    echo "ERROR: cannot reset while stack is running. Active ports: ${active_ports[*]}" >&2
    echo "Run './signal.sh stop' first, then './signal.sh reset'." >&2
    exit 1
  fi

  local db_files=(
    "$ROOT_DIR/producer/data/producer.db"
    "$ROOT_DIR/producer/data/producer.db-wal"
    "$ROOT_DIR/producer/data/producer.db-shm"
    "$ROOT_DIR/data/consumer_signals.db"
    "$ROOT_DIR/data/consumer_signals.db-wal"
    "$ROOT_DIR/data/consumer_signals.db-shm"
  )

  local f
  for f in "${db_files[@]}"; do
    if [[ -f "$f" ]]; then
      rm -f "$f"
      echo "removed $f"
    else
      echo "not found $f"
    fi
  done

  echo "Reset complete."
}

usage() {
  cat <<EOF
Usage: $(basename "$0") <start|stop|reset>

Commands:
  start   Start producer, consumer A/B, and dashboard A/B
  stop    Stop producer, consumer A/B, and dashboard A/B
  reset   Wipe local SQLite DB files (requires stack stopped)
EOF
}

main() {
  local cmd="${1:-}"
  case "$cmd" in
    start) start_stack ;;
    stop) stop_stack ;;
    reset) reset_db ;;
    *) usage; exit 1 ;;
  esac
}

main "$@"
