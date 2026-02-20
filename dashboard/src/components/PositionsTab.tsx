import { usePositions } from "@/hooks/queries";

interface PositionsTabProps {
  wallet: string;
}

export function PositionsTab({ wallet }: PositionsTabProps) {
  const { data: positions, isLoading } = usePositions(wallet);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-foreground text-sm">
        <span className="live-dot mr-2 h-1.5 w-1.5 rounded-full bg-signal-green inline-block" />
        Loading positions...
      </div>
    );
  }

  if (!positions || positions.length === 0) {
    return (
      <div className="glow-card rounded-lg p-8 text-center">
        <div className="text-muted-foreground text-sm">No open positions</div>
      </div>
    );
  }

  return (
    <div className="glow-card rounded-lg overflow-hidden">
      <div className="border-b border-[#1e2235] px-4 py-2 flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
          Open Positions
        </span>
        <span className="text-[10px] text-muted-foreground num">
          {positions.length} active
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[#1e2235]">
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold min-w-[200px]">Market</th>
              <th className="text-center px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Side</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Size</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Avg</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Current</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Value</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">P&L</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p, i) => {
              const cashPnl = p.cashPnl ?? 0;
              const pctPnl = ((p.percentPnl ?? 0) * 100).toFixed(1);
              const pnlColor = cashPnl > 0 ? "text-signal-green" : cashPnl < 0 ? "text-signal-red" : "text-foreground";

              return (
                <tr
                  key={`${p.conditionId ?? i}-${p.outcome}-${i}`}
                  className="border-b border-[#1e2235]/50 hover:bg-[#4ade8008] transition-colors"
                >
                  <td className="px-4 py-2.5 max-w-[300px] truncate">
                    {p.title ?? "---"}
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold ${
                      p.outcome === "Yes"
                        ? "bg-signal-green/15 text-signal-green border-signal-green/30"
                        : "bg-signal-red/15 text-signal-red border-signal-red/30"
                    }`}>
                      {p.outcome ?? "---"}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right num">{(p.size ?? 0).toFixed(2)}</td>
                  <td className="px-4 py-2.5 text-right num">{((p.avgPrice ?? 0) * 100).toFixed(1)}\u00A2</td>
                  <td className="px-4 py-2.5 text-right num">{((p.curPrice ?? 0) * 100).toFixed(1)}\u00A2</td>
                  <td className="px-4 py-2.5 text-right num">${(p.currentValue ?? 0).toFixed(2)}</td>
                  <td className={`px-4 py-2.5 text-right font-semibold ${pnlColor}`}>
                    <span className="num">{cashPnl >= 0 ? "+" : ""}${cashPnl.toFixed(2)}</span>
                    <span className="text-[10px] ml-1 text-muted-foreground">({pctPnl}%)</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
