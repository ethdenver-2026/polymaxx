import {
  useBalances,
  usePortfolioValue,
  usePositions,
  useSignals,
  useActivity,
  useConfig,
  useSetTradingMode,
  usePaperPositions,
  useTrades,
} from "@/hooks/queries";
import { PnLChart } from "./PnLChart";


interface PortfolioTabProps {
  wallet: string;
}

export function PortfolioTab({ wallet }: PortfolioTabProps) {
  const { data: balances, isLoading: balLoading } = useBalances();
  const { data: portfolio, isLoading: portLoading } = usePortfolioValue(wallet);
  const { data: positions } = usePositions(wallet);
  const { data: signals } = useSignals();
  const { data: activity } = useActivity(wallet);
  const { data: config } = useConfig();
  const toggleMode = useSetTradingMode();

  // Computed from real data — don't trust the Data API's portfolio value
  const clobBalance = balances?.polymarket_usdc ?? 0;
  const totalPositionValue = positions?.reduce((sum, p) => sum + (p.currentValue ?? 0), 0) ?? 0;
  const totalPositionPnl = positions?.reduce((sum, p) => sum + (p.cashPnl ?? 0), 0) ?? 0;
  const totalInitialValue = positions?.reduce((sum, p) => sum + (p.initialValue ?? 0), 0) ?? 0;
  const openCount = positions?.length ?? 0;

  const portfolioValue = clobBalance + totalPositionValue;
  const deposited = portfolio?.deposited ?? 0;
  const pnl = deposited > 0 ? portfolioValue - deposited : totalPositionPnl;
  const pnlPct = deposited > 0 ? pnl / deposited : totalInitialValue > 0 ? totalPositionPnl / totalInitialValue : 0;
  const isUp = pnl > 0;
  const isDown = pnl < 0;
  const isLoading = balLoading || portLoading;

  // Signal stats (last 24h)
  const dayAgo = Date.now() / 1000 - 24 * 3600;
  const recentSignals = signals?.filter((s) => s.received_at > dayAgo) ?? [];
  const executed24h = recentSignals.filter((s) => s.action === "executed").length;
  const skipped24h = recentSignals.filter((s) => s.action === "skipped").length;
  const hitRate = recentSignals.length > 0
    ? ((executed24h / recentSignals.length) * 100).toFixed(0)
    : "---";

  // Win rate from positions
  const winCount = positions?.filter((p) => (p.cashPnl ?? 0) > 0).length ?? 0;
  const winRate = openCount > 0 ? ((winCount / openCount) * 100).toFixed(0) : "---";

  const isLive = config?.trading_mode === "live";
  const { data: paperPositions } = usePaperPositions(!isLive);
  const { data: trades } = useTrades();

  // Paper-mode aggregates
  const paperTotalNotional = paperPositions?.reduce((s, p) => s + (p.size_usd ?? 0), 0) ?? 0;
  const paperPositionCount = paperPositions?.length ?? 0;
  const paperOpenTrades = trades?.filter((t) => t.trade_type === "paper" && t.status === "open") ?? [];
  const paperUnrealizedPnl = paperOpenTrades.reduce((s, t) => s + (t.unrealized_pnl ?? 0), 0);

  // Pick values based on mode
  const displayPortfolioValue = isLive ? portfolioValue : (config?.bankroll_usdc ?? 0);
  const displayPnl = isLive ? pnl : paperUnrealizedPnl;
  const displayPnlPct = isLive ? pnlPct : (config?.bankroll_usdc ? paperUnrealizedPnl / config.bankroll_usdc : 0);
  const displayInPositions = isLive ? totalPositionValue : paperTotalNotional;
  const displayFreeCash = isLive ? clobBalance : (config?.bankroll_usdc ?? 0) - paperTotalNotional;
  const displayOpenCount = isLive ? openCount : paperPositionCount;
  const displayPositionPnl = isLive ? totalPositionPnl : paperUnrealizedPnl;

  return (
    <div className="space-y-4">
      {/* === TIER 1: Hero strip — the number that matters most === */}
      <div className="grid grid-cols-[1fr_auto] gap-6 glow-card rounded-lg p-6"
        style={{
          borderColor: isUp ? "#4ade8025" : isDown ? "#f8717125" : undefined,
          boxShadow: isUp
            ? "inset 0 1px 0 0 #4ade8018, 0 0 40px -10px #4ade8010"
            : isDown
              ? "inset 0 1px 0 0 #f8717118, 0 0 40px -10px #f8717110"
              : undefined,
        }}
      >
        <div>
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1.5">
            {isLive ? "Portfolio Value" : "Paper Portfolio"}
          </div>
          <div className="text-4xl font-bold num tracking-tight">
            {isLoading && isLive ? (
              <span className="text-muted-foreground">---</span>
            ) : (
              `$${displayPortfolioValue.toFixed(2)}`
            )}
          </div>
          {!(isLoading && isLive) && (
            <div className="flex items-baseline gap-3 mt-1.5">
              <span
                className={`text-lg font-semibold num ${
                  displayPnl > 0 ? "text-signal-green" : displayPnl < 0 ? "text-signal-red" : "text-muted-foreground"
                }`}
              >
                {displayPnl >= 0 ? "+" : ""}${displayPnl.toFixed(2)}
              </span>
              <span
                className={`text-sm num ${
                  displayPnl > 0 ? "text-signal-green/70" : displayPnl < 0 ? "text-signal-red/70" : "text-muted-foreground"
                }`}
              >
                ({displayPnlPct >= 0 ? "+" : ""}{(displayPnlPct * 100).toFixed(2)}%)
              </span>
            </div>
          )}
        </div>

        {/* Right side: key allocation breakdown */}
        <div className="flex flex-col justify-center gap-2 min-w-[160px] border-l border-[#1e2235] pl-6">
          <div className="flex items-center justify-between gap-4">
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground">In Positions</span>
            <span className="text-sm font-semibold num">${displayInPositions.toFixed(2)}</span>
          </div>
          <div className="flex items-center justify-between gap-4">
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground">Free Cash</span>
            <span className="text-sm font-semibold num">
              {isLive && balLoading ? "---" : `$${displayFreeCash.toFixed(2)}`}
            </span>
          </div>
          <div className="h-px bg-[#1e2235] my-0.5" />
          <div className="flex items-center justify-between gap-4">
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
              {isLive ? "Deposited" : "Bankroll"}
            </span>
            <span className="text-xs num text-muted-foreground">
              {isLive ? (isLoading ? "---" : `$${deposited.toFixed(2)}`) : `$${(config?.bankroll_usdc ?? 0).toFixed(2)}`}
            </span>
          </div>
        </div>
      </div>

      {/* === TIER 2: Key metrics bar === */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-px bg-[#1e2235] rounded-lg overflow-hidden">
        <MetricCell
          label="Open Positions"
          value={displayOpenCount.toString()}
          sub={`${displayPositionPnl >= 0 ? "+" : ""}$${displayPositionPnl.toFixed(2)} unrealized`}
          subColor={displayPositionPnl >= 0 ? "text-signal-green" : "text-signal-red"}
        />
        <MetricCell
          label="Win Rate"
          value={winRate === "---" ? winRate : `${winRate}%`}
          sub={`${winCount}/${openCount} positions`}
        />
        <MetricCell
          label="24h Signals"
          value={recentSignals.length.toString()}
          sub={`${executed24h} exec / ${skipped24h} skip`}
        />
        <MetricCell
          label="Execution Rate"
          value={hitRate === "---" ? hitRate : `${hitRate}%`}
          sub="of signals received"
        />
        <div className="bg-[#0c0e14] px-4 py-3">
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">
            Mode
          </div>
          <button
            onClick={() => toggleMode.mutate(isLive ? "paper" : "live")}
            disabled={toggleMode.isPending}
            className={`text-lg font-bold num cursor-pointer transition-colors hover:opacity-80 disabled:opacity-50 ${
              isLive ? "text-signal-red" : "text-signal-amber"
            }`}
          >
            {isLive ? "LIVE" : "PAPER"}
          </button>
          <div className="text-[10px] mt-0.5 text-muted-foreground">
            Edge &gt;{config?.edge_threshold_pct ?? "---"}% &middot; click to toggle
          </div>
        </div>
      </div>

      {/* === TIER 3: P&L chart === */}
      <PnLChart activity={activity ?? []} positions={positions ?? []} />

      {/* === TIER 4: Positions + Signal feed === */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* Current positions — wider */}
        <div className="lg:col-span-3 glow-card rounded-lg overflow-hidden">
          <div className="border-b border-[#1e2235] px-4 py-2 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
              {isLive ? "Open Positions" : "Paper Positions"}
            </span>
            <span className={`text-xs font-semibold num ${displayPositionPnl >= 0 ? "text-signal-green" : "text-signal-red"}`}>
              {displayPositionPnl >= 0 ? "+" : ""}${displayPositionPnl.toFixed(2)}
            </span>
          </div>

          {isLive ? (
            /* ---- LIVE positions table ---- */
            !positions || positions.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                No open positions
              </div>
            ) : (
              <>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-[#1e2235]">
                      <th className="text-left px-4 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Market</th>
                      <th className="text-center px-3 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Side</th>
                      <th className="text-right px-3 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Size</th>
                      <th className="text-right px-3 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Avg</th>
                      <th className="text-right px-3 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Cur</th>
                      <th className="text-right px-3 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Value</th>
                      <th className="text-right px-4 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.slice(0, 8).map((p, i) => {
                      const pl = p.cashPnl ?? 0;
                      const plPct = ((p.percentPnl ?? 0) * 100).toFixed(1);
                      return (
                        <tr
                          key={`${p.conditionId ?? i}-${i}`}
                          className="border-b border-[#1e2235]/30 hover:bg-[#4ade8008] transition-colors"
                        >
                          <td className="px-4 py-2 max-w-[240px] truncate">{p.title ?? "---"}</td>
                          <td className="px-3 py-2 text-center">
                            <span className={`text-[10px] font-semibold uppercase ${
                              p.outcome === "Yes" ? "text-signal-green" : "text-signal-red"
                            }`}>
                              {p.outcome ?? "---"}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-right num">{(p.size ?? 0).toFixed(1)}</td>
                          <td className="px-3 py-2 text-right num text-muted-foreground">{((p.avgPrice ?? 0) * 100).toFixed(1)}¢</td>
                          <td className="px-3 py-2 text-right num">{((p.curPrice ?? 0) * 100).toFixed(1)}¢</td>
                          <td className="px-3 py-2 text-right num">${(p.currentValue ?? 0).toFixed(2)}</td>
                          <td className={`px-4 py-2 text-right font-semibold num ${
                            pl > 0 ? "text-signal-green" : pl < 0 ? "text-signal-red" : "text-muted-foreground"
                          }`}>
                            {pl >= 0 ? "+" : ""}${pl.toFixed(2)}
                            <span className="text-[10px] text-muted-foreground ml-1">({plPct}%)</span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {positions.length > 8 && (
                  <div className="px-4 py-2 text-[10px] text-muted-foreground text-center border-t border-[#1e2235]/30">
                    +{positions.length - 8} more positions
                  </div>
                )}
              </>
            )
          ) : (
            /* ---- TRADES table (paper mode) ---- */
            (() => {
              const paperTrades = trades?.filter((t) => t.trade_type === "paper") ?? [];
              return paperTrades.length === 0 ? (
                <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                  No paper trades &mdash; generate a signal to start
                </div>
              ) : (
                <>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-[#1e2235]">
                        <th className="text-left px-4 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Market</th>
                        <th className="text-center px-2 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">City</th>
                        <th className="text-center px-2 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Side</th>
                        <th className="text-right px-2 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Size</th>
                        <th className="text-right px-2 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Entry</th>
                        <th className="text-right px-2 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Edge</th>
                        <th className="text-right px-2 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Cur</th>
                        <th className="text-right px-2 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">P&L</th>
                        <th className="text-center px-2 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Status</th>
                        <th className="text-right px-4 py-2 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paperTrades.slice(0, 8).map((t) => {
                        const edge = t.live_edge ?? t.signal_edge ?? 0;
                        return (
                          <tr
                            key={t.id}
                            className="border-b border-[#1e2235]/30 hover:bg-[#4ade8008] transition-colors"
                          >
                            <td className="px-4 py-2 max-w-[200px] truncate">
                              {t.market_description || t.event_title || t.token_id.slice(0, 20) + "..."}
                            </td>
                            <td className="px-2 py-2 text-center text-muted-foreground">
                              {t.city ?? "---"}
                            </td>
                            <td className="px-2 py-2 text-center">
                              <span className={`text-[10px] font-semibold uppercase ${
                                t.side === "buy" ? "text-signal-green" : "text-signal-red"
                              }`}>
                                {t.side}
                              </span>
                            </td>
                            <td className="px-2 py-2 text-right num">${(t.size_usd ?? 0).toFixed(2)}</td>
                            <td className="px-2 py-2 text-right num text-muted-foreground">{((t.entry_price ?? 0) * 100).toFixed(1)}¢</td>
                            <td className={`px-2 py-2 text-right font-semibold num ${
                              edge > 0 ? "text-signal-green" : "text-muted-foreground"
                            }`}>
                              {(edge * 100).toFixed(1)}%
                            </td>
                            <td className="px-2 py-2 text-right num text-muted-foreground">
                              {t.current_price != null ? `${(t.current_price * 100).toFixed(1)}¢` : "---"}
                            </td>
                            <td className={`px-2 py-2 text-right font-semibold num ${
                              t.unrealized_pnl != null && t.unrealized_pnl > 0
                                ? "text-signal-green"
                                : t.unrealized_pnl != null && t.unrealized_pnl < 0
                                  ? "text-signal-red"
                                  : "text-muted-foreground"
                            }`}>
                              {t.unrealized_pnl != null
                                ? `${t.unrealized_pnl >= 0 ? "+" : ""}$${t.unrealized_pnl.toFixed(2)}`
                                : "---"}
                            </td>
                            <td className="px-2 py-2 text-center">
                              <span className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-[9px] uppercase tracking-wider font-semibold ${
                                t.status === "open"
                                  ? "bg-signal-green/15 text-signal-green border-signal-green/30"
                                  : t.status === "closed"
                                    ? "bg-blue-500/15 text-blue-400 border-blue-500/30"
                                    : "bg-signal-red/15 text-signal-red border-signal-red/30"
                              }`}>
                                {t.status}
                              </span>
                            </td>
                            <td className="px-4 py-2 text-right num text-muted-foreground text-[10px]">
                              {new Date(t.created_at * 1000).toLocaleTimeString([], {
                                hour: "2-digit",
                                minute: "2-digit",
                              })}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {paperTrades.length > 8 && (
                    <div className="px-4 py-2 text-[10px] text-muted-foreground text-center border-t border-[#1e2235]/30">
                      +{paperTrades.length - 8} more trades
                    </div>
                  )}
                </>
              );
            })()
          )}
        </div>

        {/* Recent signals — narrower */}
        <div className="lg:col-span-2 glow-card rounded-lg overflow-hidden">
          <div className="border-b border-[#1e2235] px-4 py-2 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
              Recent Signals
            </span>
          </div>

          {recentSignals.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">
              No signals in the last 24 hours
            </div>
          ) : (
            <div className="divide-y divide-[#1e2235]/50 max-h-[340px] overflow-y-auto">
              {recentSignals.slice(0, 12).map((s) => (
                <div
                  key={s.id}
                  className="px-4 py-2.5 flex items-center justify-between hover:bg-[#4ade8008] transition-colors"
                >
                  <div className="min-w-0 flex-1 mr-3">
                    <div className="text-xs truncate">
                      {s.description || s.token_id.slice(0, 20) + "..."}
                    </div>
                    <div className="text-[10px] text-muted-foreground num mt-0.5">
                      {new Date(s.received_at * 1000).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                      {s.live_edge != null && (
                        <span className="ml-2">
                          edge {(s.live_edge * 100).toFixed(1)}%
                        </span>
                      )}
                    </div>
                  </div>
                  <span
                    className={`shrink-0 inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold ${
                      s.action === "executed"
                        ? "bg-signal-green/15 text-signal-green border-signal-green/30"
                        : s.action === "simulated"
                          ? "bg-blue-500/15 text-blue-400 border-blue-500/30"
                          : s.action === "skipped"
                            ? "bg-purple-500/15 text-purple-400 border-purple-500/30"
                            : "bg-signal-red/15 text-signal-red border-signal-red/30"
                    }`}
                  >
                    {s.action}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function MetricCell({
  label,
  value,
  valueColor,
  sub,
  subColor,
}: {
  label: string;
  value: string;
  valueColor?: string;
  sub?: string;
  subColor?: string;
}) {
  return (
    <div className="bg-[#0c0e14] px-4 py-3">
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">
        {label}
      </div>
      <div className={`text-lg font-bold num ${valueColor ?? "text-foreground"}`}>
        {value}
      </div>
      {sub && (
        <div className={`text-[10px] mt-0.5 ${subColor ?? "text-muted-foreground"}`}>
          {sub}
        </div>
      )}
    </div>
  );
}
