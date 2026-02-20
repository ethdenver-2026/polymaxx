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
  timestamp: string;
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
}

export interface ConsumerConfig {
  trading_mode: string;
  bankroll_usdc: number;
  max_position_usd: number;
  kelly_fraction: number;
  edge_threshold_pct: number;
  daily_loss_limit_pct: number;
  wallet_address: string;
}
