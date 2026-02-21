"""Address normalization helpers shared across producer/consumer."""

from __future__ import annotations


def normalize_evm_address(address: str) -> str:
    normalized = address.strip().lower()
    if not normalized.startswith("0x") or len(normalized) != 42:
        raise ValueError(f"Invalid wallet address format: {address}")
    return normalized
