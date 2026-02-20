import { Fragment, useState } from "react";
import { useSignals } from "@/hooks/queries";
import type { StrategyCheckData } from "@/api/types";

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString([], { month: "short", day: "numeric" });
}

function pct(v: number | null): string {
  if (v === null || v === undefined) return "---";
  return `${(v * 100).toFixed(1)}%`;
}

function ActionPill({ action }: { action: string }) {
  const styles = {
    executed: "bg-signal-green/15 text-signal-green border-signal-green/30",
    skipped: "bg-signal-amber/15 text-signal-amber border-signal-amber/30",
    error: "bg-signal-red/15 text-signal-red border-signal-red/30",
  }[action] ?? "bg-muted text-muted-foreground border-border";

  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold ${styles}`}>
      {action}
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

function SkipReason({ errors }: { errors: string[] }) {
  if (!errors || errors.length === 0) return null;
  return (
    <div className="text-[11px] text-signal-amber mt-1">
      {errors[0]}
    </div>
  );
}

export function SignalsTab() {
  const { data: signals, isLoading } = useSignals();
  const [expandedId, setExpandedId] = useState<number | null>(null);

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
          {signals.length} signals
        </span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[#1e2235]">
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold w-6"></th>
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Time</th>
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold min-w-[200px]">Signal</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Model</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Sig Price</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Live Price</th>
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Sig Edge</th>
              <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Live Edge</th>
              <th className="text-right px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Action</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((s, i) => {
              const isExpanded = expandedId === s.id;
              const hasChecks = s.strategy_checks && s.strategy_checks.length > 0;

              return (
                <Fragment key={s.id}>
                  <tr
                    className={`signal-row border-b border-[#1e2235]/50 hover:bg-[#4ade8008] transition-colors ${hasChecks ? "cursor-pointer" : ""}`}
                    style={{ animationDelay: `${i * 30}ms` }}
                    onClick={() => hasChecks && setExpandedId(isExpanded ? null : s.id)}
                  >
                    <td className="px-2 py-2.5 text-center text-muted-foreground/40">
                      {hasChecks && (
                        <span className="text-[10px] select-none">{isExpanded ? "\u25BC" : "\u25B6"}</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 whitespace-nowrap text-muted-foreground">
                      <div className="num">{formatTime(s.received_at)}</div>
                      <div className="text-[10px] text-muted-foreground/50">{formatDate(s.received_at)}</div>
                    </td>
                    <td className="px-4 py-2.5 max-w-[280px]">
                      <div className="truncate">{s.description || s.token_id.slice(0, 20) + "..."}</div>
                      {s.action === "skipped" && <SkipReason errors={s.errors} />}
                    </td>
                    <td className="px-4 py-2.5 text-right num text-signal-cyan">
                      {pct(s.model_probability)}
                    </td>
                    <td className="px-4 py-2.5 text-right num">
                      {s.signal_price !== null ? `${(s.signal_price * 100).toFixed(1)}¢` : "---"}
                    </td>
                    <td className="px-4 py-2.5 text-right num">
                      {s.live_price !== null ? `${(s.live_price * 100).toFixed(1)}¢` : "---"}
                    </td>
                    <td className="px-4 py-2.5">
                      <EdgeBar edge={s.signal_edge} />
                    </td>
                    <td className="px-4 py-2.5">
                      <EdgeBar edge={s.live_edge} />
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <ActionPill action={s.action} />
                    </td>
                  </tr>
                  {isExpanded && hasChecks && (
                    <tr className="border-b border-[#1e2235]/50">
                      <td></td>
                      <td colSpan={8} className="px-4 pb-3 bg-[#0d0f1a]">
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
