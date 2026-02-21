import { useAuctions, useAuctionSmoke } from "@/hooks/queries";
import { useConfig } from "@/hooks/queries";

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString([], { month: "short", day: "numeric" });
}

function truncateId(id: string): string {
  if (id.length <= 12) return id;
  return id.slice(0, 6) + "\u2026" + id.slice(-4);
}

function OutcomePill({ outcome }: { outcome: string }) {
  const styles: Record<string, string> = {
    bid_submitted: "bg-signal-cyan/15 text-signal-cyan border-signal-cyan/30",
    won_offer: "bg-signal-green/15 text-signal-green border-signal-green/30",
    payment_succeeds: "bg-signal-green/15 text-signal-green border-signal-green/30",
    payment_failed: "bg-signal-red/15 text-signal-red border-signal-red/30",
    auction_loss: "bg-signal-amber/15 text-signal-amber border-signal-amber/30",
    auction_elapsed: "bg-muted text-muted-foreground border-border",
  };

  const style = styles[outcome] ?? "bg-muted text-muted-foreground border-border";

  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold ${style}`}>
      {outcome.replace(/_/g, " ")}
    </span>
  );
}

function isNewAuctionGroup(events: { auction_id: string }[], index: number): boolean {
  if (index === 0) return false;
  return events[index].auction_id !== events[index - 1].auction_id;
}

function SmokeButton() {
  const smoke = useAuctionSmoke();

  return (
    <button
      onClick={() => smoke.mutate()}
      disabled={smoke.isPending}
      className="px-2.5 py-1 text-[10px] uppercase tracking-wider font-semibold rounded border transition-colors bg-signal-cyan/10 text-signal-cyan border-signal-cyan/30 hover:bg-signal-cyan/20 disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {smoke.isPending ? "Seeding\u2026" : "Seed Sample Auctions"}
    </button>
  );
}

export function AuctionsTab() {
  const { data: events, isLoading } = useAuctions();
  const { data: config } = useConfig();
  const isPaper = config?.trading_mode === "paper";

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-foreground text-sm">
        <span className="live-dot mr-2 h-1.5 w-1.5 rounded-full bg-signal-green inline-block" />
        Loading auctions...
      </div>
    );
  }

  if (!events || events.length === 0) {
    return (
      <div className="glow-card rounded-lg p-8 text-center">
        <div className="text-muted-foreground text-sm">
          No auction events yet. Waiting for bids...
        </div>
        {isPaper ? (
          <div className="mt-3">
            <SmokeButton />
          </div>
        ) : (
          <div className="mt-2 text-[10px] uppercase tracking-widest text-muted-foreground/50">
            Run: python -m signal_producer.auction_smoke
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="glow-card rounded-lg overflow-hidden">
      {/* Header */}
      <div className="border-b border-[#1e2235] px-4 py-2 flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
          Auction History
        </span>
        <div className="flex items-center gap-3">
          {isPaper && <SmokeButton />}
          <span className="text-[10px] text-muted-foreground num">
            {events.length} events
          </span>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[#1e2235]">
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Time</th>
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Auction</th>
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Producer</th>
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Event</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Bid</th>
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Outcome</th>
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Winner</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Paid</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e, i) => (
              <tr
                key={e.id}
                className={`border-b hover:bg-[#4ade8008] transition-colors ${
                  isNewAuctionGroup(events, i) ? "border-t-2 border-t-[#1e2235]" : "border-b-[#1e2235]/50"
                }`}
              >
                <td className="px-4 py-2.5 whitespace-nowrap text-muted-foreground">
                  <div className="num">{formatTime(e.received_at)}</div>
                  <div className="text-[10px] text-muted-foreground/50">{formatDate(e.received_at)}</div>
                </td>
                <td className="px-4 py-2.5 font-mono text-[11px] text-foreground/70" title={e.auction_id}>
                  {truncateId(e.auction_id)}
                </td>
                <td className="px-4 py-2.5 font-mono text-[11px] text-muted-foreground">
                  {e.producer_did ? truncateId(e.producer_did) : "---"}
                </td>
                <td className="px-4 py-2.5 text-muted-foreground">
                  {e.event_id ? truncateId(e.event_id) : "---"}
                </td>
                <td className="px-4 py-2.5 text-right num text-signal-cyan">
                  {e.bid_amount !== null ? `$${e.bid_amount.toFixed(2)}` : "---"}
                </td>
                <td className="px-4 py-2.5">
                  <OutcomePill outcome={e.outcome} />
                  {e.rejection_reason && (
                    <div className="text-[10px] text-signal-amber mt-0.5">{e.rejection_reason}</div>
                  )}
                </td>
                <td className="px-4 py-2.5 font-mono text-[11px] text-muted-foreground">
                  {e.winner_did ? truncateId(e.winner_did) : "---"}
                </td>
                <td className="px-4 py-2.5 text-right num">
                  {e.winning_paid_amount !== null ? (
                    <span className="text-signal-green">${e.winning_paid_amount.toFixed(2)}</span>
                  ) : "---"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
