"""WebSocket ingestion from producer signal stream."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from urllib.parse import urlencode
from uuid import uuid4

import structlog
import websockets

from .balances import get_balances, get_payment_usdc_balance
from .bid_pricing import BidDecision, build_bid_pricing_input, normalize_bid_decision
from .config import Settings
from .consumer_engine import get_available_balance_usdc, process_signal_payload
from .db import (
    create_signal_lifecycle,
    get_signal_id_for_auction_id,
    is_consumer_reputation_sufficient,
    log_auction_event,
    log_signal,
    record_consumer_payment_failure,
    update_signal_lifecycle,
    validate_consumer_did_wallet_binding,
)
from .payment import AuctionPaymentRequest, KiteConfig, X402V2Config, process_auction_payment
from .llm_clients import BidLlmRouter

logger = structlog.get_logger()
_AUCTION_SIGNAL_IDS: dict[tuple[str, str], str] = {}


def _remember_signal_id(auction_id: str, consumer_did: str, signal_id: str) -> None:
    _AUCTION_SIGNAL_IDS[(auction_id, consumer_did)] = signal_id


def _resolve_signal_id(auction_id: str, consumer_did: str) -> str | None:
    sid = _AUCTION_SIGNAL_IDS.get((auction_id, consumer_did))
    if sid:
        return sid
    sid = get_signal_id_for_auction_id(auction_id, consumer_did=consumer_did)
    if sid:
        _AUCTION_SIGNAL_IDS[(auction_id, consumer_did)] = sid
    return sid


def _safe_update_lifecycle(auction_id: str, consumer_did: str, **kwargs) -> None:
    try:
        update_signal_lifecycle(auction_id=auction_id, consumer_did=consumer_did, **kwargs)
    except Exception as exc:
        logger.exception(
            "Failed to update signal lifecycle row",
            auction_id=auction_id,
            consumer_did=consumer_did,
            error=str(exc),
            update_fields=list(kwargs.keys()),
        )


def handle_raw_ws_message(message: str, settings: Settings) -> dict:
    """Decode raw websocket JSON, process signal, and persist result."""
    try:
        payload = json.loads(message)
    except json.JSONDecodeError as exc:
        response = {"action": "error", "errors": [f"invalid_json: {exc}"]}
        logger.error("Invalid websocket JSON payload", error=str(exc))
        return response

    try:
        response = process_signal_payload(payload, settings)
    except Exception as exc:
        logger.exception("Signal processing failed", error=str(exc))
        response = {"action": "error", "errors": [f"processing_failed: {exc}"]}

    try:
        log_signal(payload, response)
    except Exception as exc:
        logger.exception("Failed to persist consumer signal log", error=str(exc))

    return response


async def _submit_bid_for_preview(payload: dict, settings: Settings) -> dict:
    auction_id = payload.get("auction_id")
    if not auction_id:
        raise RuntimeError("SignalPreviewMessage missing auction_id")
    producer_did = payload.get("producer_did")
    event_id = None
    event_title = None
    market_group_item_title = None
    exchanges = payload.get("exchanges")
    if isinstance(exchanges, list) and exchanges:
        event_id = exchanges[0].get("event_id")
        event_title = exchanges[0].get("event_title")
        market_group_item_title = exchanges[0].get("market_group_item_title")
    consumer_did = _resolve_consumer_did(settings)

    signal_id = _resolve_signal_id(auction_id, consumer_did)
    if signal_id is None:
        signal_id = f"sig-{uuid4().hex}"
        _remember_signal_id(auction_id, consumer_did, signal_id)
        try:
            create_signal_lifecycle(
                signal_id=signal_id,
                auction_id=auction_id,
                consumer_did=consumer_did,
                producer_did=producer_did,
                event_id=event_id,
                preview_payload=payload,
            )
        except Exception as exc:
            logger.exception(
                "Failed to create lifecycle row for preview",
                auction_id=auction_id,
                signal_id=signal_id,
                error=str(exc),
            )
    else:
        _safe_update_lifecycle(
            auction_id,
            consumer_did,
            state="preview_received",
            action="pending",
            signal_payload=payload,
            producer_did=producer_did,
            event_id=event_id,
        )

    if settings.reputation_storage_backend == "0g_stub" and settings.reputation_0g_enabled:
        logger.warning(
            "0g reputation backend requested but not implemented; using local_db",
            consumer_did=consumer_did,
        )
    if not is_consumer_reputation_sufficient(consumer_did, threshold=5):
        log_auction_event(
            auction_id=auction_id,
            consumer_did=consumer_did,
            producer_did=producer_did,
            event_id=event_id,
            event_title=event_title,
            market_group_item_title=market_group_item_title,
            bid_amount=0.0,
            auction_end_utc=payload.get("auction_end_utc"),
            outcome="insufficient_reputation",
            metadata={"reason": "InsufficientReputation", "threshold": 5},
            raw_message={"type": "InsufficientReputation", "auction_id": auction_id},
        )
        _safe_update_lifecycle(
            auction_id,
            consumer_did,
            state="insufficient_reputation",
            action="skipped",
            errors=["InsufficientReputation"],
            decision_rationale="InsufficientReputation",
            bid_amount=0.0,
        )
        return {"action": "InsufficientReputation", "errors": ["InsufficientReputation"]}

    decision = await determine_bid_for_preview(payload, settings)

    # Log a signal entry so the signals page can join with auction data
    _first_ex = exchanges[0] if isinstance(exchanges, list) and exchanges else {}
    _preview_response = {
        "action": "bid_submitted" if decision.should_bid else "bid_skipped",
        "signal_price": _first_ex.get("market_price"),
        "signal_edge": _first_ex.get("edge"),
    }
    log_signal(payload, _preview_response, auction_id=auction_id)

    if not decision.should_bid:
        log_auction_event(
            auction_id=auction_id,
            consumer_did=consumer_did,
            producer_did=producer_did,
            event_id=event_id,
            event_title=event_title,
            market_group_item_title=market_group_item_title,
            bid_amount=0.0,
            auction_end_utc=payload.get("auction_end_utc"),
            outcome="bid_skipped",
            metadata={
                "rationale": decision.rationale,
                "provider": settings.bid_llm_provider,
            },
            raw_message={
                "type": "BidSkipped",
                "auction_id": auction_id,
                "reason": decision.rationale,
            },
        )
        _safe_update_lifecycle(
            auction_id,
            consumer_did,
            state="bid_skipped",
            action="skipped",
            errors=[],
            decision_rationale=decision.rationale,
            bid_amount=0.0,
        )
        logger.info("Skipping auction bid", auction_id=auction_id, reason=decision.rationale)
        return {"action": "bid_skipped", "errors": []}

    bid_amount = decision.bid_amount
    bid_url = f"{settings.producer_bid_ws_url}?{urlencode({'consumer_did': consumer_did})}"
    bid_message = {
        "type": "AuctionBidMessage",
        "version": 1,
        "auction_id": auction_id,
        "consumer_did": consumer_did,
        "wallet_address": settings.payment_wallet_address,
        "bid_amount": bid_amount,
    }
    log_auction_event(
        auction_id=auction_id,
        consumer_did=consumer_did,
        producer_did=producer_did,
        event_id=event_id,
        event_title=event_title,
        market_group_item_title=market_group_item_title,
        bid_amount=bid_amount,
        auction_end_utc=payload.get("auction_end_utc"),
        outcome="bid_submitted",
        metadata={
            "rationale": decision.rationale,
            "provider": settings.bid_llm_provider,
        },
        raw_message=bid_message,
    )
    _safe_update_lifecycle(
        auction_id,
        consumer_did,
        state="bid_submitted",
        action="pending",
        bid_amount=bid_amount,
        decision_rationale=decision.rationale,
    )
    logger.info(
        "Submitting auction bid",
        auction_id=auction_id,
        consumer_did=consumer_did,
        bid_amount=bid_amount,
    )
    async with websockets.connect(bid_url) as bid_ws:
        await bid_ws.send(json.dumps(bid_message))
        while True:
            raw = await asyncio.wait_for(
                bid_ws.recv(),
                timeout=settings.consumer_bid_timeout_seconds,
            )
            bid_response = json.loads(raw)
            response_type = bid_response.get("type")

            if response_type in {"AuctionBidRejected", "AuctionLossNotice", "AuctionNoWinner"}:
                log_auction_event(
                    auction_id=auction_id,
                    consumer_did=consumer_did,
                    producer_did=producer_did,
                    event_id=event_id,
                    event_title=event_title,
                    market_group_item_title=market_group_item_title,
                    bid_amount=bid_amount,
                    outcome=response_type,
                    rejection_reason=bid_response.get("reason"),
                    winner_did=bid_response.get("winner_did"),
                    winning_paid_amount=bid_response.get("paid_amount"),
                    raw_message=bid_response,
                )
                lifecycle_state = {
                    "AuctionBidRejected": "auction_bid_rejected",
                    "AuctionLossNotice": "auction_loss",
                    "AuctionNoWinner": "auction_no_winner",
                }.get(response_type, "auction_result")
                lifecycle_errors = []
                reason = bid_response.get("reason")
                if reason:
                    lifecycle_errors = [str(reason)]
                _safe_update_lifecycle(
                    auction_id,
                    consumer_did,
                    state=lifecycle_state,
                    action="skipped",
                    winner_did=bid_response.get("winner_did"),
                    winning_paid_amount=bid_response.get("paid_amount"),
                    errors=lifecycle_errors,
                )
                logger.info(
                    "Auction ended without win",
                    auction_id=auction_id,
                    response_type=response_type,
                )
                return {"action": response_type, "errors": []}

            if response_type == "AuctionWinNotice":
                log_auction_event(
                    auction_id=auction_id,
                    consumer_did=consumer_did,
                    producer_did=producer_did,
                    event_id=event_id,
                    event_title=event_title,
                    market_group_item_title=market_group_item_title,
                    bid_amount=bid_response.get("bid_amount"),
                    outcome="won_offer",
                    payment_url=bid_response.get("x402_payment_url"),
                    raw_message=bid_response,
                )
                _safe_update_lifecycle(
                    auction_id,
                    consumer_did,
                    state="won_offer",
                    action="pending",
                    bid_amount=bid_response.get("bid_amount"),
                    winner_did=consumer_did,
                )
                payment_result = {
                    "type": "AuctionPaymentResult",
                    "version": 1,
                    "auction_id": auction_id,
                    "consumer_did": consumer_did,
                    "payment_success": _execute_payment_for_win_notice(
                        bid_response=bid_response,
                        auction_id=auction_id,
                        settings=settings,
                        consumer_did=consumer_did,
                    ),
                }
                await bid_ws.send(json.dumps(payment_result))
                continue

            if response_type == "AuctionPaymentStatus":
                normalized_status = str(bid_response.get("status", "PAYMENT_UNKNOWN")).lower()
                log_auction_event(
                    auction_id=auction_id,
                    consumer_did=consumer_did,
                    producer_did=producer_did,
                    event_id=event_id,
                    event_title=event_title,
                    market_group_item_title=market_group_item_title,
                    bid_amount=bid_amount,
                    outcome=normalized_status,
                    raw_message=bid_response,
                )
                _safe_update_lifecycle(
                    auction_id,
                    consumer_did,
                    state=normalized_status,
                    action="pending" if normalized_status == "payment_succeeds" else "error",
                    errors=[] if normalized_status == "payment_succeeds" else [normalized_status],
                )
                continue

            if response_type == "SignalMessage":
                signal_payload = bid_response.get("signal")
                if not isinstance(signal_payload, dict):
                    raise RuntimeError("SignalMessage missing signal payload")
                _safe_update_lifecycle(
                    auction_id,
                    consumer_did,
                    state="signal_received",
                    action="pending",
                    signal_payload=signal_payload,
                )
                response = process_signal_payload(signal_payload, settings)
                try:
                    log_signal(signal_payload, response)
                except Exception as exc:
                    logger.exception(
                        "Failed to persist consumer signal log for SignalMessage",
                        auction_id=auction_id,
                        consumer_did=consumer_did,
                        error=str(exc),
                    )
                _safe_update_lifecycle(
                    auction_id,
                    consumer_did,
                    state=response.get("action", "processed"),
                    action=response.get("action"),
                    signal_payload=signal_payload,
                    signal_price=response.get("signal_price"),
                    live_price=response.get("live_price"),
                    signal_edge=response.get("signal_edge"),
                    live_edge=response.get("live_edge"),
                    order_id=response.get("order_id"),
                    errors=response.get("errors", []),
                )
                return response


async def determine_bid_for_preview(payload: dict, settings: Settings) -> BidDecision:
    if settings.trading_mode == "paper":
        balance_usdc = get_available_balance_usdc(settings)
        balances = None
        payment_usdc = balance_usdc
    else:
        balances = get_balances(
            private_key=settings.trading_wallet_private_key,
            wallet_address=settings.trading_wallet_address,
        )
        if balances.onchain_pol < settings.min_polygon_pol_for_bidding:
            rationale = (
                "insufficient_polygon_pol: "
                f"have={balances.onchain_pol:.8f}, "
                f"required={settings.min_polygon_pol_for_bidding:.8f}"
            )
            logger.info(
                "Skipping bid due to low Polygon gas balance",
                auction_id=payload.get("auction_id"),
                trading_wallet_address=settings.trading_wallet_address,
                onchain_pol=balances.onchain_pol,
                min_polygon_pol_for_bidding=settings.min_polygon_pol_for_bidding,
            )
            return BidDecision(should_bid=False, bid_amount=0.0, rationale=rationale)

        payment_usdc = get_payment_usdc_balance(
            wallet_address=settings.payment_wallet_address,
            rpc_url=settings.x402_v2_rpc_url,
            token_address=settings.x402_v2_token_address,
            token_decimals=settings.x402_v2_token_decimals,
        )
        balance_usdc = payment_usdc
    context = build_bid_pricing_input(
        preview_payload=payload,
        balance_usdc=balance_usdc,
        reputation_score=None,
    )
    router = BidLlmRouter(
        provider=settings.bid_llm_provider,
        anthropic_api_key=settings.anthropic_api_key,
        anthropic_model=settings.anthropic_bid_model,
        anthropic_temperature=settings.bid_llm_temperature,
        g0_api_key=settings.g0_api_key,
        g0_base_url=settings.g0_base_url,
        g0_model=settings.g0_bid_model,
        request_timeout_seconds=settings.bid_llm_request_timeout_seconds,
    )
    decision = await router.decide_bid(context)
    normalized = normalize_bid_decision(
        decision=decision,
        available_balance_usdc=balance_usdc,
        max_bid_amount_usdc=settings.bid_llm_max_bid_amount_usdc,
    )
    logger.info(
        "Bid decision generated",
        auction_id=context.auction_id,
        provider=settings.bid_llm_provider,
        polymarket_usdc=balances.polymarket_usdc if balances else None,
        polygon_onchain_usdc_e=balances.onchain_usdc if balances else None,
        payment_usdc=payment_usdc,
        context=asdict(context),
        decision=asdict(normalized),
    )
    return normalized


def _execute_payment_for_win_notice(
    *,
    bid_response: dict,
    auction_id: str,
    settings: Settings,
    consumer_did: str,
) -> bool:
    if settings.consumer_payment_auto_succeeds:
        logger.info("Auto-succeeding payment (consumer_payment_auto_succeeds=true)", auction_id=auction_id)
        return True
    payment_url = str(bid_response.get("x402_payment_url", "")).strip()
    bid_amount = float(bid_response.get("bid_amount", 0.0))
    selected_mode = (
        str(bid_response.get("x402_mode", settings.x402_mode)).strip()
        or settings.x402_mode
    )
    try:
        payment_request = AuctionPaymentRequest(
            auction_id=auction_id,
            consumer_did=consumer_did,
            wallet_address=settings.payment_wallet_address,
            producer_wallet_address=str(bid_response.get("producer_wallet_address", "")).strip(),
            x402_payment_url=payment_url,
            bid_amount=bid_amount,
            x402_mode=selected_mode,
        )
        kite_config = KiteConfig(
            session_url=settings.kite_session_url,
            api_key=settings.kite_api_key,
        )
        x402_v2_config = X402V2Config(
            network=settings.x402_v2_network,
            asset=settings.x402_v2_asset,
            chain_id=settings.x402_v2_chain_id,
            rpc_url=settings.x402_v2_rpc_url,
            token_address=settings.x402_v2_token_address,
            token_decimals=settings.x402_v2_token_decimals,
            siwx_challenge_url=settings.siwx_challenge_url,
            siwx_auth_url=settings.siwx_auth_url,
            siwx_app_id=settings.siwx_app_id,
            siwx_wallet_private_key=settings.payment_wallet_private_key,
        )
        success = process_auction_payment(
            request=payment_request,
            kite_config=kite_config,
            x402_v2_config=x402_v2_config,
            timeout_seconds=(
                settings.x402_v2_timeout_seconds
                if selected_mode == "x402_v2"
                else settings.kite_payment_timeout_seconds
            ),
        )
        if not success:
            record_consumer_payment_failure(
                consumer_did=consumer_did,
                auction_id=auction_id,
                reason="payment_failed",
            )
        return success
    except Exception as exc:
        logger.exception(
            "Auction payment execution failed",
            auction_id=auction_id,
            consumer_did=consumer_did,
            payment_url=payment_url,
            bid_amount=bid_amount,
            error=str(exc),
        )
        record_consumer_payment_failure(
            consumer_did=consumer_did,
            auction_id=auction_id,
            reason=f"payment_exception:{exc}",
        )
        return False


def _resolve_consumer_did(settings: Settings) -> str:
    return validate_consumer_did_wallet_binding(
        consumer_did=settings.consumer_did,
        wallet_address=settings.payment_wallet_address,
        chain_id=settings.chain_id,
    )


async def consume_producer_signals(settings: Settings) -> None:
    """Reconnect loop that consumes producer websocket signals forever."""
    ws_url = settings.producer_ws_url
    reconnect_delay = settings.producer_ws_reconnect_seconds
    logger.info("Starting producer websocket ingestion", ws_url=ws_url)

    while True:
        try:
            signal_url = f"{ws_url}?{urlencode({'consumer_did': settings.consumer_did})}"
            async with websockets.connect(signal_url) as ws:
                logger.info("Connected to producer websocket", ws_url=ws_url)
                async for message in ws:
                    payload = json.loads(message)
                    message_type = payload.get("type")
                    if message_type == "SignalPreviewMessage":
                        try:
                            await _submit_bid_for_preview(payload, settings)
                        except Exception as bid_exc:
                            logger.exception(
                                "Failed to process SignalPreviewMessage",
                                auction_id=payload.get("auction_id"),
                                error=str(bid_exc),
                            )
                        continue
                    if message_type == "AuctionResultBroadcast":
                        auction_id = payload.get("auction_id", "unknown")
                        log_auction_event(
                            auction_id=auction_id,
                            consumer_did=settings.consumer_did,
                            outcome="auction_result",
                            winner_did=payload.get("winner_did"),
                            winning_paid_amount=payload.get("paid_amount"),
                            raw_message=payload,
                        )
                        winner_did = payload.get("winner_did")
                        result_state = "auction_result"
                        if winner_did:
                            if winner_did == settings.consumer_did:
                                result_state = "auction_winner_confirmed"
                            else:
                                result_state = "auction_loser_confirmed"
                        else:
                            result_state = "auction_no_winner_confirmed"
                        _safe_update_lifecycle(
                            auction_id,
                            settings.consumer_did,
                            state=result_state,
                            winner_did=winner_did,
                            winning_paid_amount=payload.get("paid_amount"),
                        )
                        continue
                    if message_type == "SignalMessage":
                        signal_payload = payload.get("signal", {})
                        handle_raw_ws_message(json.dumps(signal_payload), settings)
                        continue
                    handle_raw_ws_message(message, settings)
        except Exception as exc:
            logger.error(
                "Producer websocket disconnected",
                ws_url=ws_url,
                reconnect_seconds=reconnect_delay,
                error=str(exc),
            )
            await asyncio.sleep(reconnect_delay)
