// Polymarket Data API types

export interface Position {
  asset: string;
  conditionId: string;
  curPrice: number;
  currentValue: number;
  initialValue: number;
  cashPnl: number;
  percentPnl: number;
  proxyWalletAddress: string;
  size: number;
  title: string;
  slug: string;
  outcome: string;
  avgPrice: number;
  market: string;
}

export interface ClosedPosition {
  conditionId: string;
  title: string;
  pnl: number;
  initialValue: number;
  cashPnl: number;
  percentPnl: number;
  outcome: string;
  endPrice: number;
  avgPrice: number;
  size: number;
}

export interface Activity {
  id: string;
  timestamp: number | string;
  type: string; // "TRADE" | "REDEEM" | "DEPOSIT" | "WITHDRAWAL"
  title: string;
  outcome: string;
  side: string;
  price: number;
  size: number;
  usdcSize: number;
}

export interface PortfolioSummary {
  portfolioValue: number;
  pnl: number;
  percentPnl: number;
  deposited: number;
}

// Consumer API types

export interface Balances {
  wallet_address: string;
  polymarket_usdc: number;
  polymarket_allowance_exchange: number;
  polymarket_allowance_neg_risk: number;
  onchain_usdc: number;
  onchain_pol: number;
  total_usdc: number;
  error?: string;
}

export interface StrategyCheckData {
  name: string;
  passed: boolean;
  detail: string;
  data: Record<string, unknown>;
}

export interface ConsumerSignal {
  id: number;
  received_at: number;
  description: string;
  event_title: string;
  market_group_item_title: string;
  token_id: string;
  side: string;
  model_probability: number | null;
  position_size_usd: number | null;
  action: string;
  signal_price: number | null;
  live_price: number | null;
  signal_edge: number | null;
  live_edge: number | null;
  order_id: string | null;
  errors: string[];
  strategy_checks: StrategyCheckData[] | null;
  city: string | null;
  event_id: string | null;
  edge: number | null;
  auction_id: string | null;
  bid_amount: number | null;
  auction_outcome: string | null;
  paid_amount: number | null;
}

export interface ConsumerConfig {
  trading_mode: string;
  bankroll_usdc: number;
  max_position_usd: number;
  kelly_fraction: number;
  edge_threshold_pct: number;
  wallet_address: string;
}

export interface PaperPosition {
  token_id: string;
  description: string;
  side: string;
  entry_price: number;
  size_usd: number;
  model_probability: number;
  edge: number;
  received_at: number;
}

export interface Trade {
  id: number;
  trade_type: "paper" | "live";
  token_id: string;
  side: string;
  entry_price: number | null;
  size_usd: number | null;
  model_probability: number | null;
  signal_edge: number | null;
  live_edge: number | null;
  order_id: string | null;
  status: "open" | "closed" | "error";
  event_title: string | null;
  market_description: string | null;
  city: string | null;
  target_date: string | null;
  created_at: number;
  closed_at: number | null;
  exit_price: number | null;
  pnl_usd: number | null;
}

export interface GenerateSignalResponse {
  ok: boolean;
  signals_found: number;
  errors: string[];
}

export interface AuctionEvent {
  id: number;
  received_at: number;
  auction_id: string;
  consumer_did: string;
  producer_did: string | null;
  event_id: string | null;
  event_title: string | null;
  market_group_item_title: string | null;
  bid_amount: number | null;
  auction_end_utc: string | null;
  outcome: string;
  rejection_reason: string | null;
  winner_did: string | null;
  winning_paid_amount: number | null;
  payment_url: string | null;
}
