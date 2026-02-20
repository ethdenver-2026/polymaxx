"""Latency-sensitive webhook API for receiving signals."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextlib import suppress

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

    execution_queue: asyncio.Queue[tuple[Signal, str]] = asyncio.Queue(
        maxsize=settings.execution_queue_maxsize
    )
    workers: list[asyncio.Task] = []
    workers_started = False
    workers_lock = asyncio.Lock()

    async def _worker() -> None:
        while True:
            signal, request_id = await execution_queue.get()
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
            finally:
                execution_queue.task_done()

    async def _ensure_workers_started() -> None:
        nonlocal workers_started
        if workers_started:
            return

        async with workers_lock:
            if workers_started:
                return
            for _ in range(settings.execution_workers):
                workers.append(asyncio.create_task(_worker()))
            workers_started = True

    async def _shutdown_workers() -> None:
        for task in workers:
            task.cancel()
        for task in workers:
            with suppress(asyncio.CancelledError):
                await task

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await _ensure_workers_started()
        try:
            yield
        finally:
            await _shutdown_workers()

    app = FastAPI(title="signal-consumer", version="0.1.0", lifespan=lifespan)

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

        if settings.trading_mode != "live":
            logger.info(
                "Signal simulated (paper mode)",
                request_id=request_id,
                trading_mode=settings.trading_mode,
                token_id=signal.token_id,
            )
            return {"status": "simulated", "request_id": request_id}

        try:
            await _ensure_workers_started()
            execution_queue.put_nowait((signal, request_id))
        except asyncio.QueueFull as e:
            logger.error(
                "Execution queue full",
                request_id=request_id,
                queue_maxsize=settings.execution_queue_maxsize,
                token_id=signal.token_id,
                error=str(e),
            )
            raise HTTPException(status_code=503, detail="execution queue is full") from e

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

