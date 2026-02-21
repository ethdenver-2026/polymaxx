# Live Test: Wallet + DID + Auction Flow

This runbook is for local live validation of producer/consumer auction flow with wallet-bound DIDs (`did:pkh`).

## Mode switch (demo)

- `PRODUCER_X402_MODE=kite` uses Kite-hosted payment flow.
- `PRODUCER_X402_MODE=x402_v2` uses producer-hosted SIWx + x402_v2 endpoints.

Both are supported. For this runbook, we use producer-owned `x402_v2`.

## 1) Generate wallets for 2 consumers + 1 producer

From repo root:

```bash
mkdir -p .secrets && chmod 700 .secrets

cd consumer
uv run python - <<'PY' > ../.secrets/local-wallets.env
from eth_account import Account

CHAIN_ID = 137
for prefix in ("CONSUMER_A", "CONSUMER_B", "PRODUCER"):
    acct = Account.create()
    addr = acct.address.lower()
    pk = acct.key.hex()
    did = f"did:pkh:eip155:{CHAIN_ID}:{addr}"
    print(f"{prefix}_PRIVATE_KEY={pk}")
    print(f"{prefix}_WALLET_ADDRESS={addr}")
    print(f"{prefix}_DID={did}")
    print()
PY

cd ..
chmod 600 .secrets/local-wallets.env
```

Load generated values:

```bash
set -a
source .secrets/local-wallets.env
set +a
```

## 2) Preflight checks

Check required keys in root `.env`:

```bash
python - <<'PY'
from pathlib import Path
p = Path(".env")
if not p.exists():
    print("missing .env")
    raise SystemExit(1)
text = p.read_text()
for k in ("ANTHROPIC_API_KEY",):
    print(k, "present" if f"{k}=" in text and f"{k}=\n" not in text else "missing_or_empty")
PY
```

Check local ports are free:

```bash
lsof -iTCP:8000 -sTCP:LISTEN
lsof -iTCP:9866 -sTCP:LISTEN
lsof -iTCP:9867 -sTCP:LISTEN
```

If ports are occupied, stop those processes or choose different ports.

## 3) Producer env (x402_v2, Kite OFF)

```bash
cat > producer/.env <<EOF
PRODUCER_DID=${PRODUCER_DID}
POLYMARKET_PRIVATE_KEY=${PRODUCER_PRIVATE_KEY}
POLYMARKET_WALLET_ADDRESS=${PRODUCER_WALLET_ADDRESS}

PRODUCER_X402_MODE=x402_v2
PRODUCER_PUBLIC_BASE_URL=http://127.0.0.1:8000
# Optional override; if omitted, producer auto-uses:
# http://127.0.0.1:8000/x402/v2/payment
# PRODUCER_X402_V2_URL=http://127.0.0.1:8000/x402/v2/payment
SIGNAL_AUCTION_TIMEOUT_SECONDS=15
SIGNAL_AUCTION_PAYMENT_TIMEOUT_SECONDS=20
EOF
```

## 4) Consumer envs (example)

Consumer A:

```bash
cat > consumer/.env.consumer-a <<EOF
CONSUMER_DID=${CONSUMER_A_DID}
CONSUMER_WALLET_ADDRESS=${CONSUMER_A_WALLET_ADDRESS}
POLYMARKET_PRIVATE_KEY=${CONSUMER_A_PRIVATE_KEY}

PRODUCER_WS_URL=ws://127.0.0.1:8000/ws/signals
PRODUCER_BID_WS_URL=ws://127.0.0.1:8000/ws/bids

BID_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=\${ANTHROPIC_API_KEY}

X402_MODE=x402_v2
X402_V2_NETWORK=base-sepolia
X402_V2_ASSET=usdc
SIWX_CHALLENGE_URL=http://127.0.0.1:8000/x402/v2/siwx/challenge
SIWX_AUTH_URL=http://127.0.0.1:8000/x402/v2/siwx/auth
SIWX_APP_ID=signal-market-demo
SIWX_WALLET_PRIVATE_KEY=${CONSUMER_A_PRIVATE_KEY}

CHAIN_ID=137
TRADING_MODE=live
EOF
```

Consumer B:

```bash
cat > consumer/.env.consumer-b <<EOF
CONSUMER_DID=${CONSUMER_B_DID}
CONSUMER_WALLET_ADDRESS=${CONSUMER_B_WALLET_ADDRESS}
POLYMARKET_PRIVATE_KEY=${CONSUMER_B_PRIVATE_KEY}

PRODUCER_WS_URL=ws://127.0.0.1:8000/ws/signals
PRODUCER_BID_WS_URL=ws://127.0.0.1:8000/ws/bids

BID_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=\${ANTHROPIC_API_KEY}

X402_MODE=x402_v2
X402_V2_NETWORK=base-sepolia
X402_V2_ASSET=usdc
SIWX_CHALLENGE_URL=http://127.0.0.1:8000/x402/v2/siwx/challenge
SIWX_AUTH_URL=http://127.0.0.1:8000/x402/v2/siwx/auth
SIWX_APP_ID=signal-market-demo
SIWX_WALLET_PRIVATE_KEY=${CONSUMER_B_PRIVATE_KEY}

CHAIN_ID=137
TRADING_MODE=live
EOF
```

## 5) Start services (three terminals)

Terminal 1:

```bash
cd producer
uv run uvicorn signal_producer.ws_server:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd consumer
cp .env.consumer-a .env
uv run python -m signal_consumer.run --host 127.0.0.1 --api-port 9866 --verbose
```

Terminal 3:

```bash
cd consumer
cp .env.consumer-b .env
uv run python -m signal_consumer.run --host 127.0.0.1 --api-port 9867 --verbose
```

## 6) Trigger live signal generation

```bash
curl -sS -X POST "http://127.0.0.1:8000/run-once?cities=nyc"
```

Expected success format:

```json
{"signals_found":<number>}
```

If `signals_found` is `0`, no qualifying market signal was emitted in that cycle.

## 7) Verify auction + payment persistence

```bash
sqlite3 data/consumer_signals.db "select datetime(received_at,'unixepoch'),auction_id,consumer_did,outcome,bid_amount,winner_did,winning_paid_amount from consumer_auction_log order by id desc limit 30;"
```

```bash
sqlite3 data/consumer_signals.db "select datetime(received_at,'unixepoch'),consumer_did,auction_id,reason,negative_delta from consumer_reputation_events order by id desc limit 20;"
```

## 8) Known hard-fail errors and meaning

- `Invalid wallet address format: 0xabc`
  - Consumer wallet format is invalid for `did:pkh` validation. Must be a 42-char `0x...` address.
- `ANTHROPIC_API_KEY is required for anthropic bid provider`
  - Consumer cannot produce bid decisions until API key is set.
- `SIWX_CHALLENGE_URL is required for x402_v2 mode` (or SIWX auth/app/private-key variants)
  - x402_v2 payment cannot run without SIWx auth configuration.
- `LLM response is not valid JSON: ...`
  - Anthropic output didn't match strict JSON format expected by bid parser.
- `[Errno 48] ... address already in use`
  - Chosen local port is occupied.

## 9) Evidence from current local run

Current run confirmed:

- Wallet-bound DID websocket connections are accepted by producer.
- Preview messages are delivered.
- Producer `AuctionWinNotice` emits `x402_mode=x402_v2` and uses `PRODUCER_X402_V2_URL`.
- Consumer exits bid/payment flow with explicit errors when LLM JSON or SIWx config is missing.

This is expected behavior and confirms configuration gating is enforced.
