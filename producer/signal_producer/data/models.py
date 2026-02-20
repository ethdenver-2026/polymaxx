"""SQLAlchemy models for data storage."""

from datetime import date, datetime

from sqlalchemy import (
    create_engine,
    Boolean,
    Column,
    Integer,
    String,
    Float,
    Date,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class Observation(Base):
    """Actual temperature observation."""

    __tablename__ = "observations"

    id = Column(Integer, primary_key=True)
    city = Column(String(50), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    high_temp = Column(Float, nullable=False)
    source = Column(String(50), nullable=False)  # 'noaa' or 'wunderground'
    collected_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('city', 'date', name='uq_city_date'),
    )


class PredictionRecord(Base):
    """Track every bucket probability prediction and its outcome.

    Used for calibration analysis: comparing model probabilities against
    actual outcomes to assess and improve forecast accuracy.

    Records ALL buckets for an event, not just traded ones.
    """

    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True)
    forecast_date = Column(Date, nullable=False)  # When forecast was made
    target_date = Column(Date, nullable=False, index=True)
    city = Column(String(50), nullable=False, index=True)

    # Bucket info
    bucket_question = Column(Text, nullable=False)
    bucket_low = Column(Float)  # None for "X or below"
    bucket_high = Column(Float)  # None for "X or above"

    # Prediction
    raw_ensemble_prob = Column(Float, nullable=False)  # Model probability
    ensemble_mean = Column(Float)  # Ensemble mean temp
    ensemble_spread = Column(Float)  # max - min spread

    # Market state at prediction time
    market_price = Column(Float)  # Price at time of prediction

    # Outcome (filled after resolution)
    actual_temp = Column(Float)  # Observed high temperature
    outcome = Column(Boolean)  # Did temp fall in this bucket?
    resolved_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            'city', 'target_date', 'bucket_question', 'forecast_date',
            name='uq_prediction',
        ),
    )


class SignalRecord(Base):
    """Every signal generated, whether traded or not.

    Named SignalRecord to avoid confusion with strategies.base.Signal dataclass.
    """

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    strategy = Column(String(50), nullable=False, index=True)
    market_id = Column(String(100), nullable=False)
    token_id = Column(String(100), nullable=False)

    # Signal data
    model_probability = Column(Float, nullable=False)
    market_price = Column(Float, nullable=False)
    edge = Column(Float, nullable=False)
    confidence = Column(Float)

    # Decision
    decision = Column(String(20), nullable=False)  # 'trade', 'skip'
    skip_reason = Column(String(100))  # 'below_threshold', 'no_liquidity', etc.

    # Link to trade if acted on
    trade_id = Column(Integer, ForeignKey('trades.id'), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    metadata_json = Column(Text)  # Strategy-specific data as JSON


class Position(Base):
    """Open position in a market."""

    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)
    strategy = Column(String(50), nullable=False, index=True)
    market_id = Column(String(100), nullable=False)
    token_id = Column(String(100), nullable=False)

    # Position state
    shares = Column(Float, nullable=False)
    cost_basis = Column(Float, nullable=False)  # Avg cost per share
    total_cost = Column(Float, nullable=False)

    # Lifecycle
    status = Column(String(20), nullable=False)  # 'open', 'closed'
    opened_at = Column(DateTime, nullable=False)
    closed_at = Column(DateTime)
    realized_pnl = Column(Float)


class Trade(Base):
    """Trade record (paper or live)."""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    mode = Column(String(10), nullable=False)  # 'paper' or 'live'
    strategy = Column(String(50), nullable=False, index=True, default="weather")
    city = Column(String(50), nullable=False)
    target_date = Column(Date, nullable=False, index=True)
    bucket_question = Column(Text, nullable=False)
    token_id = Column(String(100), nullable=False)
    side = Column(String(10), nullable=False)  # 'buy' or 'sell'
    model_prob = Column(Float, nullable=False)
    market_price = Column(Float, nullable=False)
    edge = Column(Float, nullable=False)
    position_usd = Column(Float, nullable=False)
    status = Column(String(20), nullable=False)  # 'pending', 'filled', 'cancelled', 'resolved'
    fill_price = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    # New fields for resolution and linking
    position_id = Column(Integer, ForeignKey('positions.id'), nullable=True)
    signal_id = Column(Integer, ForeignKey('signals.id'), nullable=True)
    actual_temp = Column(Float)  # For weather trades - actual observed temperature
    resolution_source = Column(String(50))  # 'gamma_api', 'manual'


def get_engine(db_path: str = "data/bot.db"):
    """Create database engine."""
    return create_engine(f"sqlite:///{db_path}")


def init_db(db_path: str = "data/bot.db"):
    """Initialize database with all tables."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return engine


def get_session(engine):
    """Get a new database session."""
    Session = sessionmaker(bind=engine)
    return Session()
