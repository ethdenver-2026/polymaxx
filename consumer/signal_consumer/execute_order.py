"""
Execute an order on Polymarket after a successful simulation.

Runs simulate_order first. If simulation passes, posts the signed order
to the CLOB. Prints execution results including order ID and fill status.

When consuming a signal (--signal), the consumer fetches the **live** market
price from the CLOB orderbook and recalculates edge before executing.  If the
edge has fallen below the threshold the trade is skipped.

Usage:
    python -m signal_consumer.execute_order \
        --token-id <CLOB_TOKEN_ID> \
        --side buy \
        --price 0.50 \
        --size 10

    # From a signal JSON file (uses live price + edge check):
    python -m signal_consumer.execute_order --signal signal.json

    # Skip simulation (if you already validated):
    python -m signal_consumer.execute_order --signal signal.json --skip-simulation
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from py_clob_client.clob_types import (
    OrderArgs,
    OrderType,
    PartialCreateOrderOptions,
)
from py_clob_client.order_builder.constants import BUY, SELL

from .polymarket import init_client, get_live_price
from .simulate_order import SimulationResult, simulate_order

# Polymarket minimum order size
MIN_ORDER_SIZE = 5


@dataclass
class ExecutionResult:
    """Result of an order execution."""

    success: bool
    simulation: SimulationResult
    order_id: str | None
    status: str | None
    errors: list[str]
    # Signal-aware fields
    signal_price: float | None = None   # Original price from signal
    live_price: float | None = None     # Live price at execution time
    signal_edge: float | None = None    # Original edge from signal
    live_edge: float | None = None      # Recalculated edge at execution time

    def print_report(self):
        # Print simulation first
        self.simulation.print_report()

        status = "SUCCESS" if self.success else "FAILED"
        print(f"{'='*60}")
        print(f"  Order Execution: {status}")
        print(f"{'='*60}")

        if self.signal_price is not None:
            print(f"  Signal Price:  ${self.signal_price:.4f}")
            print(f"  Live Price:    ${self.live_price:.4f}")
            print(f"  Signal Edge:   {self.signal_edge*100:.1f}%")
            print(f"  Live Edge:     {self.live_edge*100:.1f}%")

        if self.order_id:
            print(f"  Order ID:  {self.order_id}")
        if self.status:
            print(f"  Status:    {self.status}")

        if self.errors:
            print(f"\n  Errors:")
            for err in self.errors:
                print(f"    - {err}")

        print(f"{'='*60}\n")

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "simulation": self.simulation.to_dict(),
            "order_id": self.order_id,
            "status": self.status,
            "errors": self.errors,
            "signal_price": self.signal_price,
            "live_price": self.live_price,
            "signal_edge": self.signal_edge,
            "live_edge": self.live_edge,
        }


def _round_to_tick(price: float, tick_size: str) -> float:
    """Round a price down to the nearest valid tick."""
    tick = float(tick_size)
    return math.floor(price / tick) * tick


def execute_order(
    token_id: str,
    side: str,
    price: float,
    size: float,
    order_type: str = "GTC",
    skip_simulation: bool = False,
) -> ExecutionResult:
    """
    Simulate then execute an order on Polymarket.

    1. Runs simulation (orderbook check, order signing)
    2. If simulation passes, posts the order to the CLOB
    """
    errors: list[str] = []

    if size < MIN_ORDER_SIZE:
        size = float(MIN_ORDER_SIZE)

    # --- Step 1: Simulate ---
    if skip_simulation:
        sim = SimulationResult(
            success=True,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            tick_size="0.01",
            neg_risk=False,
            best_ask=None,
            best_bid=None,
            spread=None,
            would_fill=False,
            fill_price=None,
            estimated_cost_usd=price * size,
            order_signed=False,
            errors=[],
        )
    else:
        sim = simulate_order(token_id, side, price, size)

    if not sim.success:
        return ExecutionResult(
            success=False,
            simulation=sim,
            order_id=None,
            status=None,
            errors=["Simulation failed, order not posted"] + sim.errors,
        )

    # --- Step 2: Execute ---
    try:
        client = init_client()
    except Exception as e:
        return ExecutionResult(
            success=False,
            simulation=sim,
            order_id=None,
            status=None,
            errors=[f"Client init failed: {e}"],
        )

    otype_map = {
        "GTC": OrderType.GTC,
        "FOK": OrderType.FOK,
        "GTD": OrderType.GTD,
    }
    otype = otype_map.get(order_type.upper(), OrderType.GTC)

    side_const = BUY if side.lower() == "buy" else SELL

    try:
        resp = client.create_and_post_order(
            OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side_const,
            ),
            options=PartialCreateOrderOptions(
                tick_size=sim.tick_size,
                neg_risk=sim.neg_risk,
            ),
        )

        order_id = resp.get("orderID")
        status = resp.get("status")

        if not order_id:
            errors.append(f"No orderID in response: {resp}")

        return ExecutionResult(
            success=bool(order_id),
            simulation=sim,
            order_id=order_id,
            status=status,
            errors=errors,
        )

    except Exception as e:
        return ExecutionResult(
            success=False,
            simulation=sim,
            order_id=None,
            status=None,
            errors=[f"Order execution failed: {e}"],
        )


def execute_signal(
    signal_path: str,
    order_type: str = "GTC",
    skip_simulation: bool = False,
    edge_threshold: float | None = None,
) -> ExecutionResult:
    """Execute a trade from a signal JSON file with live price validation.

    Uses the shared polymarket utilities for client init and live price fetch.
    """
    if edge_threshold is None:
        edge_threshold = float(os.environ.get("EDGE_THRESHOLD_PCT", "8")) / 100

    data = json.loads(Path(signal_path).read_text())
    token_id = data["token_id"]
    side = data.get("side", "buy")
    signal_price = data["market_price"]
    model_prob = data["model_probability"]
    signal_edge = data.get("edge", model_prob - signal_price)
    position_size_usd = data["position_size_usd"]

    # Fetch live price
    try:
        client = init_client()
    except Exception as e:
        sim = SimulationResult(
            success=False, token_id=token_id, side=side, price=signal_price,
            size=0, tick_size="0.01", neg_risk=False, best_ask=None,
            best_bid=None, spread=None, would_fill=False, fill_price=None,
            estimated_cost_usd=0, order_signed=False,
            errors=[f"Client init failed: {e}"],
        )
        return ExecutionResult(
            success=False, simulation=sim, order_id=None, status=None,
            errors=[f"Client init failed: {e}"],
            signal_price=signal_price, live_price=None,
            signal_edge=signal_edge, live_edge=None,
        )

    live_price = get_live_price(client, token_id, side)
    if live_price is None:
        live_price = signal_price

    live_edge = model_prob - live_price

    if live_edge < edge_threshold:
        sim = SimulationResult(
            success=False, token_id=token_id, side=side, price=live_price,
            size=0, tick_size="0.01", neg_risk=False, best_ask=None,
            best_bid=None, spread=None, would_fill=False, fill_price=None,
            estimated_cost_usd=0, order_signed=False,
            errors=[f"Live edge {live_edge*100:.1f}% below threshold {edge_threshold*100:.1f}%"],
        )
        return ExecutionResult(
            success=False, simulation=sim, order_id=None, status=None,
            errors=[f"Edge evaporated: signal={signal_edge*100:.1f}%, live={live_edge*100:.1f}%, threshold={edge_threshold*100:.1f}%"],
            signal_price=signal_price, live_price=live_price,
            signal_edge=signal_edge, live_edge=live_edge,
        )

    size = position_size_usd / live_price
    if size < MIN_ORDER_SIZE:
        size = float(MIN_ORDER_SIZE)

    result = execute_order(
        token_id=token_id,
        side=side,
        price=live_price,
        size=size,
        order_type=order_type,
        skip_simulation=skip_simulation,
    )
    result.signal_price = signal_price
    result.live_price = live_price
    result.signal_edge = signal_edge
    result.live_edge = live_edge
    return result


def _parse_signal_file(path: str) -> dict:
    """Parse a signal JSON file into order params (for manual --token-id style)."""
    data = json.loads(Path(path).read_text())
    return {
        "token_id": data["token_id"],
        "side": data.get("side", "buy"),
        "price": data["market_price"],
        "size": data["position_size_usd"] / data["market_price"],
    }


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Execute a Polymarket order")
    parser.add_argument("--token-id", help="CLOB token ID")
    parser.add_argument("--side", default="buy", choices=["buy", "sell"])
    parser.add_argument("--price", type=float, help="Limit price (0-1)")
    parser.add_argument("--size", type=float, help="Number of shares")
    parser.add_argument("--signal", help="Path to signal JSON file")
    parser.add_argument(
        "--order-type",
        default="GTC",
        choices=["GTC", "FOK", "GTD"],
        help="Order type (default: GTC)",
    )
    parser.add_argument(
        "--skip-simulation",
        action="store_true",
        help="Skip simulation and execute directly",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.signal:
        # Signal-aware path: live price check + edge validation
        result = execute_signal(
            signal_path=args.signal,
            order_type=args.order_type,
            skip_simulation=args.skip_simulation,
        )
    elif args.token_id and args.price and args.size:
        # Manual path: use exact params provided
        result = execute_order(
            token_id=args.token_id,
            side=args.side,
            price=args.price,
            size=args.size,
            order_type=args.order_type,
            skip_simulation=args.skip_simulation,
        )
    else:
        parser.error("Provide either --signal or --token-id, --price, and --size")

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        result.print_report()

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
