"""
Check wallet balances on Polymarket (CLOB) and on-chain (Polygon).

Usage as CLI:
    python -m signal_consumer.balances

Usage as library:
    from signal_consumer.balances import get_balances
    b = get_balances()
    print(b.polymarket_usdc)
    print(b.onchain_usdc)
    print(b.onchain_matic)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

# USDC.e on Polygon: https://polygonscan.com/token/0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
USDC_E_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC_E_DECIMALS = 6

# POL (native gas token) decimals
POL_DECIMALS = 18

# Public Polygon RPC
POLYGON_RPC = "https://polygon-bor-rpc.publicnode.com"


@dataclass
class Balances:
    """Wallet balances across Polymarket and on-chain."""

    wallet_address: str

    # Polymarket CLOB balances
    polymarket_usdc: float  # USDC.e deposited in Polymarket
    polymarket_allowance_exchange: float  # Allowance for the exchange contract
    polymarket_allowance_neg_risk: float  # Allowance for the neg risk exchange

    # On-chain Polygon balances
    onchain_usdc: float  # USDC.e in wallet on Polygon
    onchain_pol: float  # POL (gas token) in wallet

    def print_report(self):
        print(f"\n{'='*50}")
        print(f"  Balances for {self.wallet_address[:8]}...{self.wallet_address[-6:]}")
        print(f"{'='*50}")
        print(f"  Polymarket (CLOB):")
        print(f"    USDC.e:     ${self.polymarket_usdc:.6f}")
        print(f"    Allowance:  ${self.polymarket_allowance_exchange:.2f} (exchange)")
        print(f"                ${self.polymarket_allowance_neg_risk:.2f} (neg risk)")
        print(f"  On-chain (Polygon):")
        print(f"    USDC.e:     ${self.onchain_usdc:.6f}")
        print(f"    POL:        {self.onchain_pol:.4f}")
        print(f"  Total USDC.e: ${self.polymarket_usdc + self.onchain_usdc:.6f}")
        print(f"{'='*50}\n")

    def to_dict(self) -> dict:
        return {
            "wallet_address": self.wallet_address,
            "polymarket_usdc": self.polymarket_usdc,
            "polymarket_allowance_exchange": self.polymarket_allowance_exchange,
            "polymarket_allowance_neg_risk": self.polymarket_allowance_neg_risk,
            "onchain_usdc": self.onchain_usdc,
            "onchain_pol": self.onchain_pol,
            "total_usdc": self.polymarket_usdc + self.onchain_usdc,
        }


def _get_polymarket_balance(
    private_key: str,
    wallet_address: str,
    host: str,
    chain_id: int,
) -> tuple[float, float, float]:
    """
    Get USDC.e balance and allowances from Polymarket CLOB.

    Returns (balance, exchange_allowance, neg_risk_allowance).
    """
    sig_type = int(os.environ.get("POLYMARKET_SIGNATURE_TYPE", "2"))

    temp_client = ClobClient(host, key=private_key, chain_id=chain_id)
    creds = temp_client.create_or_derive_api_creds()

    client = ClobClient(
        host,
        key=private_key,
        chain_id=chain_id,
        creds=creds,
        signature_type=sig_type,
        funder=wallet_address,
    )

    result = client.get_balance_allowance(
        BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=sig_type)
    )

    balance = int(result.get("balance", "0")) / 10**USDC_E_DECIMALS
    allowances = result.get("allowances", {})

    # The allowances dict maps contract addresses to allowance amounts
    allowance_values = [int(v) / 10**USDC_E_DECIMALS for v in allowances.values()]

    exchange_allowance = allowance_values[0] if len(allowance_values) > 0 else 0.0
    neg_risk_allowance = allowance_values[1] if len(allowance_values) > 1 else 0.0

    return balance, exchange_allowance, neg_risk_allowance


def _eth_call(rpc_url: str, to: str, data: str) -> str:
    """Make an eth_call to a contract."""
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
        "id": 1,
    }
    resp = httpx.post(rpc_url, json=payload, timeout=10)
    result = resp.json()
    if "error" in result:
        raise RuntimeError(f"RPC error: {result['error']}")
    return result["result"]


def _get_eth_balance(rpc_url: str, address: str) -> str:
    """Get native token (POL) balance."""
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getBalance",
        "params": [address, "latest"],
        "id": 1,
    }
    resp = httpx.post(rpc_url, json=payload, timeout=10)
    result = resp.json()
    if "error" in result:
        raise RuntimeError(f"RPC error: {result['error']}")
    return result["result"]


def _get_onchain_balances(
    wallet_address: str,
    rpc_url: str = POLYGON_RPC,
) -> tuple[float, float]:
    """
    Get on-chain USDC.e and POL balances on Polygon.

    Returns (usdc_balance, pol_balance).
    """
    # ERC20 balanceOf(address) selector: 0x70a08231
    # Pad address to 32 bytes
    addr_padded = wallet_address.lower().replace("0x", "").zfill(64)
    calldata = "0x70a08231" + addr_padded

    usdc_hex = _eth_call(rpc_url, USDC_E_ADDRESS, calldata)
    usdc_balance = int(usdc_hex, 16) / 10**USDC_E_DECIMALS

    pol_hex = _get_eth_balance(rpc_url, wallet_address)
    pol_balance = int(pol_hex, 16) / 10**POL_DECIMALS

    return usdc_balance, pol_balance


def get_balances(
    private_key: str | None = None,
    wallet_address: str | None = None,
) -> Balances:
    """
    Get all balances for the configured wallet.

    Args:
        private_key: Polymarket private key (reads from env if not provided)
        wallet_address: Wallet address (reads from env if not provided)

    Returns:
        Balances dataclass with all balance info
    """
    if not private_key:
        private_key = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
    if not wallet_address:
        wallet_address = os.environ.get("POLYMARKET_WALLET_ADDRESS", "")

    if not private_key:
        raise RuntimeError("POLYMARKET_PRIVATE_KEY not set")
    if not wallet_address:
        raise RuntimeError("POLYMARKET_WALLET_ADDRESS not set")

    host = os.environ.get("CLOB_API_URL", "https://clob.polymarket.com")
    chain_id = int(os.environ.get("CHAIN_ID", "137"))

    poly_balance, exchange_allow, neg_risk_allow = _get_polymarket_balance(
        private_key, wallet_address, host, chain_id
    )

    onchain_usdc, onchain_pol = _get_onchain_balances(wallet_address)

    return Balances(
        wallet_address=wallet_address,
        polymarket_usdc=poly_balance,
        polymarket_allowance_exchange=exchange_allow,
        polymarket_allowance_neg_risk=neg_risk_allow,
        onchain_usdc=onchain_usdc,
        onchain_pol=onchain_pol,
    )


def main():
    load_dotenv()

    import argparse

    parser = argparse.ArgumentParser(description="Check Polymarket & on-chain balances")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    balances = get_balances()

    if args.json:
        print(json.dumps(balances.to_dict(), indent=2))
    else:
        balances.print_report()


if __name__ == "__main__":
    main()
