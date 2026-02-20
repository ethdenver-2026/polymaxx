"""Latency-sensitive webhook API for receiving signals."""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import FastAPI, HTTPException

from signal_schema import Signal

from .config import get_settings
from .polymarket import execute_weather_signal_market_buy


def create_app() -> FastAPI:
    settings = get_settings()

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logger = structlog.get_logger()

    app = FastAPI(title="signal-consumer", version="0.1.0")

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.post("/webhook/signal")
    async def webhook_signal(signal: Signal):
        request_id = str(uuid.uuid4())

        if signal.strategy != "weather":
            raise HTTPException(status_code=400, detail=f"unsupported strategy: {signal.strategy!r}")

        if signal.edge < settings.weather_edge_threshold:
            logger.info(
                "Signal skipped (below threshold)",
                request_id=request_id,
                edge=signal.edge,
                threshold=settings.weather_edge_threshold,
                token_id=signal.token_id,
            )
            return {"status": "skipped", "request_id": request_id}

        logger.info(
            "Signal accepted",
            request_id=request_id,
            edge=signal.edge,
            threshold=settings.weather_edge_threshold,
            token_id=signal.token_id,
            position_size_usd=signal.position_size_usd,
        )

        async def _execute():
            try:
                await asyncio.to_thread(
                    execute_weather_signal_market_buy,
                    settings=settings,
                    signal=signal,
                    request_id=request_id,
                )
            except Exception as e:
                # Fail loudly; do not swallow execution errors.
                logger.error(
                    "Signal execution failed",
                    request_id=request_id,
                    error=str(e),
                    exc_info=True,
                )

        # Don't block the webhook on trade execution.
        asyncio.create_task(_execute())

        return {"status": "accepted", "request_id": request_id}

    return app


app = create_app()


def main() -> None:
    """
    Dev entrypoint.

    Preferred production launch:
      uvicorn signal_consumer.api:app --host 0.0.0.0 --port 8001 --loop uvloop
    """
    import uvicorn

    uvicorn.run(
        "signal_consumer.api:app",
        host="0.0.0.0",
        port=8001,
        log_level="info",
        loop="uvloop",
    )

