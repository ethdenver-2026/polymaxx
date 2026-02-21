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


class TrackedEvent(Base):
    """
    A weather event being tracked by the producer.

    Events transition through: active -> resolved/expired (never deleted).
    """

    __tablename__ = "tracked_events"

    id = Column(Integer, primary_key=True)
    event_id = Column(String(100), nullable=False, unique=True, index=True)
    title = Column(Text, nullable=False)
    city = Column(String(50), nullable=False, index=True)
    target_date = Column(Date, nullable=False, index=True)
    resolution_source = Column(Text)  # e.g., wunderground URL

    # Lifecycle
    status = Column(String(20), nullable=False, index=True)  # 'active', 'resolved', 'expired'
    resolved_at = Column(DateTime)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TrackedMarket(Base):
    """
    A temperature range market within an event.

    Each market has YES/NO tokens and tracks current price.
    """

    __tablename__ = "tracked_markets"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey('tracked_events.id'), nullable=False, index=True)
    question = Column(Text, nullable=False)
    low_temp = Column(Float)  # None for "X or below"
    high_temp = Column(Float)  # None for "X or above"
    yes_token_id = Column(String(100), nullable=False, index=True)
    no_token_id = Column(String(100), nullable=False)
    active = Column(Boolean, nullable=False, default=True)

    # Current prices (updated via CLOB websocket, in-memory cache is primary)
    yes_price = Column(Float)
    no_price = Column(Float)
    price_timestamp = Column(DateTime)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TrackedForecast(Base):
    """
    Ensemble forecast data for an event.

    Latest forecast is used for signal generation.
    """

    __tablename__ = "tracked_forecasts"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey('tracked_events.id'), nullable=False, index=True)
    forecast_source = Column(String(20), nullable=False)  # 'open_meteo', 'noaa'
    forecast_time = Column(DateTime, nullable=False)

    # Ensemble stats
    ensemble_mean = Column(Float, nullable=False)
    ensemble_std = Column(Float)
    ensemble_min = Column(Float)
    ensemble_max = Column(Float)

    # Raw member data (stored as JSON for flexibility)
    member_highs_json = Column(Text)  # JSON array of 31 floats

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


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

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    metadata_json = Column(Text)  # Strategy-specific data as JSON


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
