import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  ReferenceLine,
} from "recharts";
import type { Activity } from "@/api/types";
import type { Position } from "@/api/types";

interface PnLChartProps {
  activity: Activity[];
  positions: Position[];
}

interface DataPoint {
  time: number;
  label: string;
  pnl: number;
}

function buildPnLSeries(activity: Activity[], positions: Position[]): DataPoint[] {
  // Build cumulative P&L from trade activity
  // BUY = spend USDC (negative), SELL/REDEEM = receive USDC (positive)
  const trades = activity
    .filter((a) => a.timestamp && (a.type === "TRADE" || a.type === "REDEEM"))
    .map((a) => ({
      time: new Date(a.timestamp).getTime(),
      usdc: a.usdcSize ?? 0,
      type: a.type,
      side: a.side,
    }))
    .sort((a, b) => a.time - b.time);

  if (trades.length === 0) {
    // Fall back to positions snapshot if no trade history
    if (positions.length === 0) return [];

    const now = Date.now();
    const sorted = [...positions].sort(
      (a, b) => (a.cashPnl ?? 0) - (b.cashPnl ?? 0)
    );

    let cumulative = 0;
    const points: DataPoint[] = [
      { time: now - 3600_000, label: "Start", pnl: 0 },
    ];

    sorted.forEach((p, i) => {
      cumulative += p.cashPnl ?? 0;
      points.push({
        time: now - 3600_000 + ((i + 1) / sorted.length) * 3600_000,
        label: (p.title ?? "Position").slice(0, 30),
        pnl: cumulative,
      });
    });

    return points;
  }

  // Compute cumulative cash flow
  let cumulative = 0;
  const points: DataPoint[] = [];

  for (const t of trades) {
    if (t.type === "REDEEM") {
      cumulative += t.usdc;
    } else if (t.side === "SELL") {
      cumulative += t.usdc;
    } else {
      // BUY — cost
      cumulative -= t.usdc;
    }

    points.push({
      time: t.time,
      label: new Date(t.time).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      }),
      pnl: cumulative,
    });
  }

  // Add current unrealized P&L from open positions as the final point
  const unrealizedPnl = positions.reduce(
    (sum, p) => sum + (p.cashPnl ?? 0),
    0
  );
  if (positions.length > 0) {
    points.push({
      time: Date.now(),
      label: "Now",
      pnl: cumulative + unrealizedPnl,
    });
  }

  return points;
}

function CustomTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: DataPoint }>;
}) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  const isUp = d.pnl >= 0;

  return (
    <div className="rounded-md border border-[#1e2235] bg-[#0c0e14] px-3 py-2 shadow-lg">
      <div className="text-[10px] text-muted-foreground mb-1">{d.label}</div>
      <div
        className={`text-sm font-bold num ${isUp ? "text-signal-green" : "text-signal-red"}`}
      >
        {isUp ? "+" : ""}${d.pnl.toFixed(2)}
      </div>
    </div>
  );
}

export function PnLChart({ activity, positions }: PnLChartProps) {
  const data = useMemo(
    () => buildPnLSeries(activity, positions),
    [activity, positions]
  );

  if (data.length < 2) {
    return (
      <div className="glow-card rounded-lg px-4 py-6 text-center">
        <div className="text-sm text-muted-foreground">
          Not enough trade data for chart
        </div>
        <div className="text-[10px] text-muted-foreground/50 mt-1">
          P&L chart will appear after trades are executed
        </div>
      </div>
    );
  }

  const minPnl = Math.min(...data.map((d) => d.pnl));
  const maxPnl = Math.max(...data.map((d) => d.pnl));
  const lastPnl = data[data.length - 1].pnl;
  const isUp = lastPnl >= 0;

  const strokeColor = isUp ? "#4ade80" : "#f87171";
  const fillId = isUp ? "pnlGradientGreen" : "pnlGradientRed";

  return (
    <div className="glow-card rounded-lg overflow-hidden">
      <div className="border-b border-[#1e2235] px-4 py-2 flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
          P&L Over Time
        </span>
        <span
          className={`text-xs font-semibold num ${isUp ? "text-signal-green" : "text-signal-red"}`}
        >
          {isUp ? "+" : ""}${lastPnl.toFixed(2)}
        </span>
      </div>
      <div className="px-2 pt-3 pb-1">
        <ResponsiveContainer width="100%" height={160}>
          <AreaChart
            data={data}
            margin={{ top: 4, right: 8, left: 0, bottom: 0 }}
          >
            <defs>
              <linearGradient id="pnlGradientGreen" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#4ade80" stopOpacity={0.25} />
                <stop offset="100%" stopColor="#4ade80" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="pnlGradientRed" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f87171" stopOpacity={0.05} />
                <stop offset="100%" stopColor="#f87171" stopOpacity={0.2} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="#1e223530"
              vertical={false}
            />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 9, fill: "#64748b", fontFamily: "var(--font-mono)" }}
              axisLine={{ stroke: "#1e2235" }}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fontSize: 9, fill: "#64748b", fontFamily: "var(--font-mono)" }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: number) => `$${v.toFixed(0)}`}
              domain={[
                Math.min(minPnl * 1.1, -0.5),
                Math.max(maxPnl * 1.1, 0.5),
              ]}
              width={45}
            />
            <Tooltip
              content={<CustomTooltip />}
              cursor={{ stroke: "#4ade8030", strokeWidth: 1 }}
            />
            <ReferenceLine y={0} stroke="#64748b30" strokeDasharray="3 3" />
            <Area
              type="monotone"
              dataKey="pnl"
              stroke={strokeColor}
              strokeWidth={1.5}
              fill={`url(#${fillId})`}
              dot={false}
              activeDot={{
                r: 3,
                fill: strokeColor,
                stroke: "#0c0e14",
                strokeWidth: 2,
              }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
