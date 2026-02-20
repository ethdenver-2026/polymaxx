import {
  useBalances,
  usePortfolioValue,
  usePositions,
  useSignals,
  useActivity,
} from "@/hooks/queries";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
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

  const pnl = portfolio?.pnl ?? 0;
  const pnlPct = portfolio?.percentPnl ?? 0;
  const isUp = pnl > 0;
  const isDown = pnl < 0;

  // Last 6h signals
  const sixHoursAgo = Date.now() / 1000 - 6 * 3600;
  const recentSignals = signals?.filter((s) => s.received_at > sixHoursAgo) ?? [];
  const recentExecuted = recentSignals.filter((s) => s.action === "executed");
  const recentSkipped = recentSignals.filter((s) => s.action === "skipped");

  // Position totals
  const totalPositionValue = positions?.reduce((sum, p) => sum + (p.currentValue ?? 0), 0) ?? 0;
  const totalPositionPnl = positions?.reduce((sum, p) => sum + (p.cashPnl ?? 0), 0) ?? 0;

  return (
    <div className="space-y-4">
      {/* Hero P&L strip */}
      <div
        className={`glow-card rounded-lg p-5 ${
          isUp
            ? "border-signal-green/20"
            : isDown
              ? "border-signal-red/20"
              : ""
        }`}
        style={{
          boxShadow: isUp
            ? "inset 0 1px 0 0 #4ade8018, 0 0 30px -10px #4ade8010"
            : isDown
              ? "inset 0 1px 0 0 #f8717118, 0 0 30px -10px #f8717110"
              : undefined,
        }}
      >
        <div className="flex items-start justify-between">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">
              Total P&L
            </div>
            <div className="flex items-baseline gap-3">
              <span
                className={`text-4xl font-bold num ${
                  isUp ? "text-signal-green" : isDown ? "text-signal-red" : "text-foreground"
                }`}
              >
                {portLoading ? "---" : `${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}`}
              </span>
              {!portLoading && (
                <span
                  className={`text-sm num ${
                    isUp ? "text-signal-green/70" : isDown ? "text-signal-red/70" : "text-muted-foreground"
                  }`}
                >
                  {pnlPct >= 0 ? "+" : ""}{(pnlPct * 100).toFixed(2)}%
                </span>
              )}
            </div>
            <div className="text-[11px] text-muted-foreground mt-1">
              {isUp ? "You're in the green" : isDown ? "You're in the red" : "Breakeven"}
            </div>
          </div>
          <div
            className={`p-2 rounded-lg ${
              isUp
                ? "bg-signal-green/10"
                : isDown
                  ? "bg-signal-red/10"
                  : "bg-muted"
            }`}
          >
            {isUp ? (
              <TrendingUp className="h-6 w-6 text-signal-green" />
            ) : isDown ? (
              <TrendingDown className="h-6 w-6 text-signal-red" />
            ) : (
              <Minus className="h-6 w-6 text-muted-foreground" />
            )}
          </div>
        </div>
      </div>

      {/* P&L Chart */}
      <PnLChart activity={activity ?? []} positions={positions ?? []} />

      {/* Key metrics row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricCard
          label="CLOB Balance"
          value={
            balLoading
              ? "---"
              : balances?.error
                ? "ERR"
                : `$${(balances?.polymarket_usdc ?? 0).toFixed(2)}`
          }
          sub="Free cash"
        />
        <MetricCard
          label="In Positions"
          value={`$${totalPositionValue.toFixed(2)}`}
          sub={`${positions?.length ?? 0} open`}
        />
        <MetricCard
          label="Portfolio Value"
          value={
            portLoading ? "---" : `$${(portfolio?.portfolioValue ?? 0).toFixed(2)}`
          }
          sub="Total"
        />
        <MetricCard
          label="On-Chain"
          value={
            balLoading ? "---" : `${(balances?.onchain_pol ?? 0).toFixed(4)} POL`
          }
          sub={balances ? `$${(balances.onchain_usdc ?? 0).toFixed(2)} USDC` : undefined}
        />
      </div>

      {/* Two-column: Positions + Last 6h */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Current positions */}
        <div className="glow-card rounded-lg overflow-hidden">
          <div className="border-b border-[#1e2235] px-4 py-2 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
              Current Positions
            </span>
            <span className={`text-xs font-semibold num ${totalPositionPnl >= 0 ? "text-signal-green" : "text-signal-red"}`}>
              {totalPositionPnl >= 0 ? "+" : ""}${totalPositionPnl.toFixed(2)}
            </span>
          </div>

          {!positions || positions.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-muted-foreground">
              No open positions
            </div>
          ) : (
            <div className="divide-y divide-[#1e2235]/50">
              {positions.slice(0, 6).map((p, i) => {
                const pnl = p.cashPnl ?? 0;
                return (
                  <div
                    key={`${p.conditionId ?? i}-${i}`}
                    className="px-4 py-2.5 flex items-center justify-between hover:bg-[#4ade8008] transition-colors"
                  >
                    <div className="min-w-0 flex-1 mr-4">
                      <div className="text-xs truncate">{p.title ?? "---"}</div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className={`text-[10px] font-semibold uppercase ${
                          p.outcome === "Yes" ? "text-signal-green" : "text-signal-red"
                        }`}>
                          {p.outcome ?? "---"}
                        </span>
                        <span className="text-[10px] text-muted-foreground num">
                          {(p.size ?? 0).toFixed(1)} @ {((p.avgPrice ?? 0) * 100).toFixed(0)}c
                        </span>
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className="text-xs num">${(p.currentValue ?? 0).toFixed(2)}</div>
                      <div className={`text-[10px] font-semibold num ${
                        pnl > 0 ? "text-signal-green" : pnl < 0 ? "text-signal-red" : "text-muted-foreground"
                      }`}>
                        {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                      </div>
                    </div>
                  </div>
                );
              })}
              {positions.length > 6 && (
                <div className="px-4 py-2 text-[10px] text-muted-foreground text-center">
                  +{positions.length - 6} more positions
                </div>
              )}
            </div>
          )}
        </div>

        {/* Last 6 hours */}
        <div className="glow-card rounded-lg overflow-hidden">
          <div className="border-b border-[#1e2235] px-4 py-2 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
              Last 6 Hours
            </span>
            <span className="text-[10px] text-muted-foreground num">
              {recentSignals.length} signals
            </span>
          </div>

          {/* 6h summary stats */}
          <div className="grid grid-cols-3 border-b border-[#1e2235]/50">
            <div className="px-4 py-3 text-center border-r border-[#1e2235]/50">
              <div className="text-lg font-bold num">{recentSignals.length}</div>
              <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Received</div>
            </div>
            <div className="px-4 py-3 text-center border-r border-[#1e2235]/50">
              <div className="text-lg font-bold num text-signal-green">{recentExecuted.length}</div>
              <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Executed</div>
            </div>
            <div className="px-4 py-3 text-center">
              <div className="text-lg font-bold num text-signal-amber">{recentSkipped.length}</div>
              <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Skipped</div>
            </div>
          </div>

          {/* Recent signal feed */}
          {recentSignals.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-muted-foreground">
              No signals in the last 6 hours
            </div>
          ) : (
            <div className="divide-y divide-[#1e2235]/50 max-h-[260px] overflow-y-auto">
              {recentSignals.slice(0, 8).map((s) => (
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
                      {s.signal_edge != null && (
                        <span className="ml-2">
                          edge: {(s.signal_edge * 100).toFixed(1)}%
                        </span>
                      )}
                    </div>
                  </div>
                  <span
                    className={`shrink-0 inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold ${
                      s.action === "executed"
                        ? "bg-signal-green/15 text-signal-green border-signal-green/30"
                        : s.action === "skipped"
                          ? "bg-signal-amber/15 text-signal-amber border-signal-amber/30"
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

function MetricCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="glow-card rounded-lg p-4">
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground mb-2">
        {label}
      </div>
      <div className="text-lg font-bold num">{value}</div>
      {sub && (
        <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>
      )}
    </div>
  );
}
