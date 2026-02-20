import { useActivity } from "@/hooks/queries";

interface ActivityTabProps {
  wallet: string;
}

export function ActivityTab({ wallet }: ActivityTabProps) {
  const { data: activity, isLoading } = useActivity(wallet);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-foreground text-sm">
        <span className="live-dot mr-2 h-1.5 w-1.5 rounded-full bg-signal-green inline-block" />
        Loading activity...
      </div>
    );
  }

  if (!activity || activity.length === 0) {
    return (
      <div className="glow-card rounded-lg p-8 text-center">
        <div className="text-muted-foreground text-sm">No recent activity</div>
      </div>
    );
  }

  return (
    <div className="glow-card rounded-lg overflow-hidden">
      <div className="border-b border-[#1e2235] px-4 py-2 flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
          Trade History
        </span>
        <span className="text-[10px] text-muted-foreground num">
          {activity.length} events
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[#1e2235]">
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Time</th>
              <th className="text-center px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Type</th>
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold min-w-[200px]">Market</th>
              <th className="text-center px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Side</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Price</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Size</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">USDC</th>
            </tr>
          </thead>
          <tbody>
            {activity.map((a, i) => (
              <tr
                key={a.id || i}
                className="border-b border-[#1e2235]/50 hover:bg-[#4ade8008] transition-colors"
              >
                <td className="px-4 py-2.5 whitespace-nowrap text-muted-foreground num">
                  {new Date(typeof a.timestamp === "number" ? a.timestamp * 1000 : a.timestamp).toLocaleString([], {
                    month: "short", day: "numeric",
                    hour: "2-digit", minute: "2-digit",
                  })}
                </td>
                <td className="px-4 py-2.5 text-center">
                  <span className="inline-flex items-center rounded-full border border-border bg-muted px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">
                    {a.type}
                  </span>
                </td>
                <td className="px-4 py-2.5 max-w-[300px] truncate">{a.title}</td>
                <td className="px-4 py-2.5 text-center">
                  {a.side && (
                    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold ${
                      a.side === "BUY"
                        ? "bg-signal-green/15 text-signal-green border-signal-green/30"
                        : "bg-signal-red/15 text-signal-red border-signal-red/30"
                    }`}>
                      {a.side}
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right num">
                  {a.price ? `${(a.price * 100).toFixed(1)}¢` : "---"}
                </td>
                <td className="px-4 py-2.5 text-right num">
                  {a.size ? a.size.toFixed(2) : "---"}
                </td>
                <td className="px-4 py-2.5 text-right num">
                  {a.usdcSize ? `$${a.usdcSize.toFixed(2)}` : "---"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
