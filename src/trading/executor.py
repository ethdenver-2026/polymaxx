"""Trade execution logic - paper and live modes."""

from datetime import datetime
from dataclasses import dataclass
import structlog

from ..config import Settings
from ..data.models import Trade, get_engine, get_session, init_db
from ..strategies.base import Signal


logger = structlog.get_logger()


@dataclass
class ExecutionResult:
    """Result of a trade execution attempt."""

    success: bool
    trade_id: int | None
    message: str
    fill_price: float | None = None


class RiskManager:
    """Manages risk limits and kill switches."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.last_reset_date = datetime.utcnow().date()

    def _maybe_reset_daily(self):
        """Reset daily counters if it's a new day."""
        today = datetime.utcnow().date()
        if today != self.last_reset_date:
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.last_reset_date = today

    def check_can_trade(self, signal: Signal) -> tuple[bool, str]:
        """Check if we can execute this trade given risk limits."""
        self._maybe_reset_daily()

        # Check daily loss limit
        loss_limit = self.settings.bankroll_usdc * (self.settings.daily_loss_limit_pct / 100)
        if self.daily_pnl < -loss_limit:
            return False, f"Daily loss limit hit: ${abs(self.daily_pnl):.2f} > ${loss_limit:.2f}"

        # Check position size
        if signal.position_size_usd > self.settings.max_position_usd:
            return False, f"Position too large: ${signal.position_size_usd:.2f} > ${self.settings.max_position_usd:.2f}"

        # Check edge threshold
        if signal.edge < (self.settings.edge_threshold_pct / 100):
            return False, f"Edge too low: {signal.edge_pct:.1f}% < {self.settings.edge_threshold_pct:.1f}%"

        return True, "OK"

    def record_trade_result(self, pnl: float):
        """Record a trade result for risk tracking."""
        self._maybe_reset_daily()
        self.daily_pnl += pnl
        self.daily_trades += 1


class TradeExecutor:
    """Executes trades in paper or live mode."""

    def __init__(self, settings: Settings, db_path: str = "data/bot.db"):
        self.settings = settings
        self.db_path = db_path
        self.risk_manager = RiskManager(settings)

        # Initialize database
        self.engine = init_db(db_path)

    def execute(self, signal: Signal) -> ExecutionResult:
        """Execute a trade based on the signal."""
        # Check risk limits
        can_trade, reason = self.risk_manager.check_can_trade(signal)
        if not can_trade:
            logger.warning("Trade blocked by risk manager", reason=reason)
            return ExecutionResult(success=False, trade_id=None, message=reason)

        if self.settings.trading_mode == "paper":
            return self._execute_paper(signal)
        else:
            return self._execute_live(signal)

    def _execute_paper(self, signal: Signal) -> ExecutionResult:
        """Execute a paper trade (simulation only)."""
        session = get_session(self.engine)

        # Extract city from metadata for weather trades
        city = signal.metadata.get("city", "unknown") if signal.metadata else "unknown"

        try:
            # Create trade record
            trade = Trade(
                mode="paper",
                city=city,
                target_date=signal.target_date,
                bucket_question=signal.description,
                token_id=signal.token_id,
                side="buy",
                model_prob=signal.model_probability,
                market_price=signal.market_price,
                edge=signal.edge,
                position_usd=signal.position_size_usd,
                status="filled",  # Paper trades always fill
                fill_price=signal.market_price,
                created_at=datetime.utcnow(),
            )
            session.add(trade)
            session.commit()

            trade_id = trade.id

            logger.info(
                "Paper trade executed",
                trade_id=trade_id,
                strategy=signal.strategy,
                date=str(signal.target_date),
                description=signal.description[:50],
                position=f"${signal.position_size_usd:.2f}",
                edge=f"{signal.edge_pct:.1f}%",
            )

            return ExecutionResult(
                success=True,
                trade_id=trade_id,
                message="Paper trade filled",
                fill_price=signal.market_price,
            )

        except Exception as e:
            session.rollback()
            logger.error("Failed to record paper trade", error=str(e))
            return ExecutionResult(success=False, trade_id=None, message=str(e))

        finally:
            session.close()

    def _execute_live(self, signal: Signal) -> ExecutionResult:
        """Execute a live trade on Polymarket."""
        # TODO: Implement live trading using py-clob-client
        # For now, just log and return error
        logger.warning(
            "Live trading not implemented",
            strategy=signal.strategy,
            position=f"${signal.position_size_usd:.2f}",
        )
        return ExecutionResult(
            success=False,
            trade_id=None,
            message="Live trading not yet implemented",
        )

    def get_pending_trades(self) -> list[Trade]:
        """Get all pending trades waiting for resolution."""
        session = get_session(self.engine)
        try:
            trades = session.query(Trade).filter(
                Trade.status.in_(["pending", "filled"])
            ).all()
            return trades
        finally:
            session.close()

    def resolve_trade(self, trade_id: int, won: bool) -> float:
        """Resolve a trade and calculate P&L."""
        session = get_session(self.engine)
        try:
            trade = session.query(Trade).filter(Trade.id == trade_id).first()
            if not trade:
                return 0.0

            # Calculate P&L
            if won:
                # Win: we get back position / fill_price
                pnl = trade.position_usd * (1 - trade.fill_price) / trade.fill_price
            else:
                # Lose: we lose the position
                pnl = -trade.position_usd

            trade.pnl = pnl
            trade.status = "resolved"
            trade.resolved_at = datetime.utcnow()
            session.commit()

            self.risk_manager.record_trade_result(pnl)

            logger.info(
                "Trade resolved",
                trade_id=trade_id,
                won=won,
                pnl=f"${pnl:.2f}",
            )

            return pnl

        finally:
            session.close()
