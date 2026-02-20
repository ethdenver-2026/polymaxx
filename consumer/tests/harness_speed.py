"""Local speed harness for webhook ingestion (no Polymarket dependency).

Runs the FastAPI app in-process using ASGITransport and drives simulated
weather signals through /webhook/signal to measure ingestion latency.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import time
from dataclasses import dataclass
from datetime import date
from statistics import mean

from httpx import ASGITransport, AsyncClient

from signal_schema import MarketType, Signal, SignalMetadata

import signal_consumer.api as api_module


@dataclass(frozen=True)
class HarnessConfig:
    total_requests: int
    concurrency: int
    edge: float
    warmup_requests: int


def build_signal_json(edge: float) -> dict:
    # Simulated signal payload; no external calls.
    signal = Signal(
        strategy="weather",
        market_type=MarketType.POLYMARKET,
        market_id="sim-market-nyc-temp",
        token_id="sim-token-yes",
        description="Simulated weather mispricing signal",
        target_date=date.today(),
        model_probability=min(0.999, 0.5 + edge),
        market_price=0.5,
        edge=edge,
        confidence=0.95,
        position_size_usd=1.0,
        expected_value=edge,
        metadata=SignalMetadata(city="nyc", bucket_low=40, bucket_high=41),
    )
    return signal.model_dump(mode="json")


def percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    rank = p * (len(sorted_vals) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (rank - lo)


async def run_harness(config: HarnessConfig) -> None:
    # Replace live execution with a deterministic no-op so we only benchmark
    # webhook parsing/routing/dispatch overhead.
    def _no_op_execute(*, settings, signal, request_id):
        return {"status": "simulated", "request_id": request_id}

    api_module.execute_weather_signal_market_buy = _no_op_execute
    app = api_module.create_app()

    payload = build_signal_json(config.edge)

    latencies_ms: list[float] = []
    accepted = 0
    skipped = 0
    failed = 0

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://harness") as client:
        # Warmup to stabilize jitters and loop scheduling.
        for _ in range(config.warmup_requests):
            resp = await client.post("/webhook/signal", json=payload)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Warmup request failed: status={resp.status_code}, body={resp.text}"
                )

        sem = asyncio.Semaphore(config.concurrency)

        async def one_request() -> None:
            nonlocal accepted, skipped, failed
            async with sem:
                t0 = time.perf_counter()
                resp = await client.post("/webhook/signal", json=payload)
                dt_ms = (time.perf_counter() - t0) * 1000.0
                latencies_ms.append(dt_ms)

                if resp.status_code != 200:
                    failed += 1
                    return

                status = resp.json().get("status")
                if status == "accepted":
                    accepted += 1
                elif status == "skipped":
                    skipped += 1
                else:
                    failed += 1

        t_start = time.perf_counter()
        await asyncio.gather(*(one_request() for _ in range(config.total_requests)))
        elapsed_s = time.perf_counter() - t_start

    if not latencies_ms:
        raise RuntimeError("No latency samples were collected.")

    sorted_lats = sorted(latencies_ms)
    print("")
    print("=== Webhook Speed Harness Results ===")
    print(f"total_requests: {config.total_requests}")
    print(f"concurrency:    {config.concurrency}")
    print(f"warmup:         {config.warmup_requests}")
    print(f"edge:           {config.edge:.4f}")
    print(f"elapsed_sec:    {elapsed_s:.4f}")
    print(f"throughput_rps: {config.total_requests / elapsed_s:.2f}")
    print(f"latency_ms_p50: {percentile(sorted_lats, 0.50):.3f}")
    print(f"latency_ms_p95: {percentile(sorted_lats, 0.95):.3f}")
    print(f"latency_ms_p99: {percentile(sorted_lats, 0.99):.3f}")
    print(f"latency_ms_avg: {mean(latencies_ms):.3f}")
    print(f"accepted:       {accepted}")
    print(f"skipped:        {skipped}")
    print(f"failed:         {failed}")
    print("=====================================")
    print("")

    if failed > 0:
        raise RuntimeError(f"Harness observed {failed} failed responses.")


def parse_args() -> HarnessConfig:
    parser = argparse.ArgumentParser(description="Webhook local speed harness")
    parser.add_argument("--total-requests", type=int, default=5000)
    parser.add_argument("--concurrency", type=int, default=200)
    parser.add_argument("--edge", type=float, default=0.03)
    parser.add_argument("--warmup-requests", type=int, default=200)
    args = parser.parse_args()

    if args.total_requests <= 0:
        raise ValueError("--total-requests must be > 0")
    if args.concurrency <= 0:
        raise ValueError("--concurrency must be > 0")
    if args.warmup_requests < 0:
        raise ValueError("--warmup-requests must be >= 0")

    return HarnessConfig(
        total_requests=args.total_requests,
        concurrency=args.concurrency,
        edge=args.edge,
        warmup_requests=args.warmup_requests,
    )


def main() -> None:
    config = parse_args()
    asyncio.run(run_harness(config))


if __name__ == "__main__":
    main()

