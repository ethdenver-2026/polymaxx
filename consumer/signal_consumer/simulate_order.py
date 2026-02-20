"""
Simulate an order on Polymarket without executing it.

Connects to the CLOB API, fetches market data (orderbook, tick size, neg risk),
builds and signs the order, then reports what would happen — without posting.

Usage:
    python -m signal_consumer.simulate_order \
        --token-id <CLOB_TOKEN_ID> \
        --side buy \
        --price 0.50 \
        --size 10

    # Or from a signal JSON file:
    python -m signal_consumer.simulate_order --signal signal.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions
from py_clob_client.order_builder.constants import BUY, SELL

from .polymarket import init_client

# Polymarket minimum order value in USD
MIN_ORDER_USD = 1.0


@dataclass
class SimulationResult:
    """Result of an order simulation."""

    success: bool
    token_id: str
    side: str
    price: float
    size: float
    tick_size: str
    neg_risk: bool
    best_ask: float | None
    best_bid: float | None
    spread: float | None
    would_fill: bool
    fill_price: float | None
    estimated_cost_usd: float
    order_signed: bool
    errors: list[str]

    def print_report(self):
        status = "PASS" if self.success else "FAIL"
        print(f"\n{'='*60}")
        print(f"  Order Simulation: {status}")
        print(f"{'='*60}")
        print(f"  Token ID:    {self.token_id[:20]}...{self.token_id[-10:]}")
        print(f"  Side:        {self.side.upper()}")
        print(f"  Price:       ${self.price:.4f}")
        print(f"  Size:        {self.size}")
        print(f"  Tick Size:   {self.tick_size}")
        print(f"  Neg Risk:    {self.neg_risk}")
        print(f"  Best Bid:    ${self.best_bid:.4f}" if self.best_bid else "  Best Bid:    N/A")
        print(f"  Best Ask:    ${self.best_ask:.4f}" if self.best_ask else "  Best Ask:    N/A")
        print(f"  Spread:      ${self.spread:.4f}" if self.spread else "  Spread:      N/A")
        print(f"  Would Fill:  {'Yes' if self.would_fill else 'No (rests on book)'}")
        if self.fill_price is not None:
            print(f"  Fill Price:  ${self.fill_price:.4f}")
        print(f"  Est. Cost:   ${self.estimated_cost_usd:.2f}")
        print(f"  Order Signed:{' Yes' if self.order_signed else ' No'}")

        if self.errors:
            print(f"\n  Errors:")
            for err in self.errors:
                print(f"    - {err}")

        print(f"{'='*60}\n")

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "token_id": self.token_id,
            "side": self.side,
            "price": self.price,
            "size": self.size,
            "tick_size": self.tick_size,
            "neg_risk": self.neg_risk,
            "best_ask": self.best_ask,
            "best_bid": self.best_bid,
            "spread": self.spread,
            "would_fill": self.would_fill,
            "fill_price": self.fill_price,
            "estimated_cost_usd": self.estimated_cost_usd,
            "order_signed": self.order_signed,
            "errors": self.errors,
        }


def simulate_order(
    token_id: str,
    side: str,
    price: float,
    size: float,
) -> SimulationResult:
    """
    Simulate an order: fetch market data, build/sign the order, check fill.

    Does NOT post the order.
    """
    errors: list[str] = []
    best_ask = best_bid = spread = fill_price = None
    would_fill = False
    order_signed = False
    tick_size = "0.01"
    neg_risk = False

    min_size = MIN_ORDER_USD / price if price > 0 else 0
    if size < min_size:
        errors.append(f"Size {size:.1f} below minimum (${MIN_ORDER_USD:.0f} worth = {min_size:.1f} shares), adjusting")
        size = min_size

    side_const = BUY if side.lower() == "buy" else SELL

    # --- Connect to CLOB ---
    try:
        client = init_client()
    except Exception as e:
        return SimulationResult(
            success=False,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            tick_size=tick_size,
            neg_risk=neg_risk,
            best_ask=None,
            best_bid=None,
            spread=None,
            would_fill=False,
            fill_price=None,
            estimated_cost_usd=price * size,
            order_signed=False,
            errors=[f"Client init failed: {e}"],
        )

    # --- Fetch market params ---
    try:
        tick_size = client.get_tick_size(token_id)
    except Exception as e:
        errors.append(f"Failed to fetch tick size: {e}")

    try:
        neg_risk = client.get_neg_risk(token_id)
    except Exception as e:
        errors.append(f"Failed to fetch neg_risk: {e}")

    # --- Fetch orderbook ---
    try:
        book = client.get_order_book(token_id)
        asks = book.asks if book.asks else []
        bids = book.bids if book.bids else []

        if asks:
            best_ask = float(asks[0].price)
        if bids:
            best_bid = float(bids[0].price)
        if best_ask is not None and best_bid is not None:
            spread = best_ask - best_bid

        # Check if order would cross the spread (immediate fill)
        if side_const == BUY and best_ask is not None:
            if price >= best_ask:
                would_fill = True
                fill_price = best_ask  # Price improvement: fill at ask
        elif side_const == SELL and best_bid is not None:
            if price <= best_bid:
                would_fill = True
                fill_price = best_bid

    except Exception as e:
        errors.append(f"Failed to fetch orderbook: {e}")

    # --- Build and sign order (but do NOT post) ---
    try:
        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=size,
            side=side_const,
        )
        options = PartialCreateOrderOptions(
            tick_size=tick_size,
            neg_risk=neg_risk,
        )
        _signed_order = client.create_order(order_args, options)
        order_signed = True
    except Exception as e:
        errors.append(f"Order signing failed: {e}")

    estimated_cost = price * size
    success = order_signed and len(errors) == 0

    return SimulationResult(
        success=success,
        token_id=token_id,
        side=side,
        price=price,
        size=size,
        tick_size=tick_size,
        neg_risk=neg_risk,
        best_ask=best_ask,
        best_bid=best_bid,
        spread=spread,
        would_fill=would_fill,
        fill_price=fill_price,
        estimated_cost_usd=estimated_cost,
        order_signed=order_signed,
        errors=errors,
    )


def _parse_signal_file(path: str) -> dict:
    """Parse a signal JSON file into order params."""
    data = json.loads(Path(path).read_text())
    return {
        "token_id": data["token_id"],
        "side": data.get("side", "buy"),
        "price": data["market_price"],
        "size": data["position_size_usd"] / data["market_price"],
    }


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Simulate a Polymarket order")
    parser.add_argument("--token-id", help="CLOB token ID")
    parser.add_argument("--side", default="buy", choices=["buy", "sell"])
    parser.add_argument("--price", type=float, help="Limit price (0-1)")
    parser.add_argument("--size", type=float, help="Number of shares")
    parser.add_argument("--signal", help="Path to signal JSON file")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.signal:
        params = _parse_signal_file(args.signal)
    elif args.token_id and args.price and args.size:
        params = {
            "token_id": args.token_id,
            "side": args.side,
            "price": args.price,
            "size": args.size,
        }
    else:
        parser.error("Provide either --signal or --token-id, --price, and --size")

    result = simulate_order(**params)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        result.print_report()

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
