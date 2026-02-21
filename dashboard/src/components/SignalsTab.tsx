import { Fragment, useMemo, useState } from "react";
import { useSignals } from "@/hooks/queries";
import type { ConsumerSignal, StrategyCheckData } from "@/api/types";

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString([], { month: "short", day: "numeric" });
}

function ActionPill({ action }: { action: string }) {
  const styles = {
    executed: "bg-signal-green/15 text-signal-green border-signal-green/30",
    simulated: "bg-signal-green/15 text-signal-green border-signal-green/30",
    skipped: "bg-signal-amber/15 text-signal-amber border-signal-amber/30",
    error: "bg-signal-red/15 text-signal-red border-signal-red/30",
  }[action] ?? "bg-muted text-muted-foreground border-border";

  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold ${styles}`}>
      {action}
    </span>
  );
}

function OutcomePill({ outcome }: { outcome: string }) {
  const styles: Record<string, string> = {
    bid_submitted: "bg-signal-cyan/15 text-signal-cyan border-signal-cyan/30",
    bid_skipped: "bg-muted text-muted-foreground border-border",
    won_offer: "bg-signal-green/15 text-signal-green border-signal-green/30",
    payment_succeeds: "bg-signal-green/15 text-signal-green border-signal-green/30",
    payment_failed: "bg-signal-red/15 text-signal-red border-signal-red/30",
    AuctionLossNotice: "bg-signal-amber/15 text-signal-amber border-signal-amber/30",
    AuctionBidRejected: "bg-signal-red/15 text-signal-red border-signal-red/30",
    AuctionNoWinner: "bg-muted text-muted-foreground border-border",
  };
  const style = styles[outcome] ?? "bg-muted text-muted-foreground border-border";

  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold ${style}`}>
      {outcome.replace(/_/g, " ")}
    </span>
  );
}

function EdgeBar({ edge }: { edge: number | null }) {
  if (edge === null || edge === undefined) return <span className="text-muted-foreground">---</span>;
  const pctVal = edge * 100;
  const isPositive = pctVal > 0;
  const width = Math.min(Math.abs(pctVal) * 2, 100);

  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 rounded-full bg-[#1e2235] overflow-hidden">
        <div
          className={`h-full rounded-full ${isPositive ? "bg-signal-green" : "bg-signal-red"}`}
          style={{ width: `${width}%` }}
        />
      </div>
      <span className={`num text-xs ${isPositive ? "text-signal-green" : "text-signal-red"}`}>
        {pctVal > 0 ? "+" : ""}{pctVal.toFixed(1)}%
      </span>
    </div>
  );
}

function CheckIcon({ passed }: { passed: boolean }) {
  if (passed) {
    return <span className="text-signal-green text-xs">&#10003;</span>;
  }
  return <span className="text-signal-red text-xs">&#10007;</span>;
}

function StrategyChecks({ checks }: { checks: StrategyCheckData[] }) {
  return (
    <div className="flex flex-col gap-1.5 py-2">
      {checks.map((c, i) => (
        <div key={i} className="flex items-start gap-2 text-[11px]">
          <CheckIcon passed={c.passed} />
          <span className="text-muted-foreground font-mono uppercase text-[10px] w-20 shrink-0">
            {c.name}
          </span>
          <span className={c.passed ? "text-foreground/70" : "text-signal-amber"}>
            {c.detail}
          </span>
        </div>
      ))}
    </div>
  );
}

function getEventTitle(s: ConsumerSignal): string {
  if (s.event_title) return s.event_title;
  // Fallback: parse from description
  const match = s.description.match(/highest temperature in (.+?) (?:be .+? )?on (.+?)\?/i);
  if (match) return `Highest temp in ${match[1]}, ${match[2]}`;
  if (s.city) return `Weather signal — ${s.city}`;
  return s.description;
}

function getMarketLabel(s: ConsumerSignal): string {
  if (s.market_group_item_title) return s.market_group_item_title;
  // Fallback: parse bucket from description
  const match = s.description.match(/be ((?:between )?\d+.*?)(?:\s+on\s)/i);
  if (match) return match[1];
  return "";
}

interface EventGroup {
  key: string;
  title: string;
  bestSignal: ConsumerSignal;
  bucketCount: number;
  received_at: number;
}

function groupSignalsByEvent(signals: ConsumerSignal[]): EventGroup[] {
  const groups = new Map<string, ConsumerSignal[]>();

  for (const s of signals) {
    const key = s.event_id || `_solo_${s.id}`;
    const existing = groups.get(key);
    if (existing) {
      existing.push(s);
    } else {
      groups.set(key, [s]);
    }
  }

  const result: EventGroup[] = [];
  for (const [key, groupSignals] of groups) {
    const bestSignal = groupSignals.reduce((best, s) => {
      const bestEdge = best.signal_edge ?? -Infinity;
      const sEdge = s.signal_edge ?? -Infinity;
      return sEdge > bestEdge ? s : best;
    });

    const title = key.startsWith("_solo_")
      ? bestSignal.description
      : getEventTitle(bestSignal);

    const received_at = Math.min(...groupSignals.map((s) => s.received_at));

    result.push({ key, title, bestSignal, bucketCount: groupSignals.length, received_at });
  }

  result.sort((a, b) => b.received_at - a.received_at);
  return result;
}

const COL_COUNT = 8;

export function SignalsTab() {
  const { data: signals, isLoading } = useSignals();
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const eventGroups = useMemo(() => {
    if (!signals) return [];
    return groupSignalsByEvent(signals);
  }, [signals]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-foreground text-sm">
        <span className="live-dot mr-2 h-1.5 w-1.5 rounded-full bg-signal-green inline-block" />
        Loading signals...
      </div>
    );
  }

  if (!signals || signals.length === 0) {
    return (
      <div className="glow-card rounded-lg p-8 text-center">
        <div className="text-muted-foreground text-sm">
          No signals received. Waiting for producer...
        </div>
        <div className="mt-2 text-[10px] uppercase tracking-widest text-muted-foreground/50">
          Run: python test_e2e.py --cities nyc,chicago
        </div>
      </div>
    );
  }

  return (
    <div className="glow-card rounded-lg overflow-hidden">
      {/* Header */}
      <div className="border-b border-[#1e2235] px-4 py-2 flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
          Signal Feed
        </span>
        <span className="text-[10px] text-muted-foreground num">
          {eventGroups.length} events
        </span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[#1e2235]">
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold w-6"></th>
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Time</th>
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Event</th>
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Market</th>
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Edge</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Bid</th>
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Outcome</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Action</th>
            </tr>
          </thead>
          <tbody>
            {eventGroups.map((group, i) => {
              const s = group.bestSignal;
              const hasChecks = s.strategy_checks && s.strategy_checks.length > 0;
              const isExpanded = expandedKey === group.key;
              const isSolo = group.key.startsWith("_solo_");

              return (
                <Fragment key={group.key}>
                  <tr
                    className={`signal-row border-b border-[#1e2235]/50 hover:bg-[#4ade8008] transition-colors ${hasChecks ? "cursor-pointer" : ""}`}
                    style={{ animationDelay: `${i * 30}ms` }}
                    onClick={() => hasChecks && setExpandedKey(isExpanded ? null : group.key)}
                  >
                    <td className="px-2 py-2.5 text-center text-muted-foreground/40">
                      {hasChecks && (
                        <span className="text-[10px] select-none">{isExpanded ? "\u25BC" : "\u25B6"}</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 whitespace-nowrap text-muted-foreground">
                      <div className="num">{formatTime(group.received_at)}</div>
                      <div className="text-[10px] text-muted-foreground/50">{formatDate(group.received_at)}</div>
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="font-medium">{group.title}</div>
                      {!isSolo && (
                        <div className="text-[10px] text-muted-foreground/60 mt-0.5">
                          {group.bucketCount} buckets
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-muted-foreground">
                      {getMarketLabel(s) || "---"}
                    </td>
                    <td className="px-4 py-2.5">
                      <EdgeBar edge={s.signal_edge} />
                    </td>
                    <td className="px-4 py-2.5 text-right num text-signal-cyan">
                      {s.bid_amount != null ? `$${s.bid_amount.toFixed(2)}` : "---"}
                    </td>
                    <td className="px-4 py-2.5">
                      {s.auction_outcome ? <OutcomePill outcome={s.auction_outcome} /> : <span className="text-muted-foreground">---</span>}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <ActionPill action={s.action} />
                    </td>
                  </tr>

                  {/* Strategy checks for best bucket */}
                  {isExpanded && hasChecks && (
                    <tr className="border-b border-[#1e2235]/50">
                      <td></td>
                      <td colSpan={COL_COUNT - 1} className="px-4 pb-3 bg-[#0d0f1a]">
                        <div className="text-[10px] uppercase tracking-widest text-muted-foreground/60 pt-2 pb-1">
                          Strategy Checks
                        </div>
                        <StrategyChecks checks={s.strategy_checks!} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
