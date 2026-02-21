import { useConfig } from "@/hooks/queries";

export function SettingsTab() {
  const { data: config, isLoading } = useConfig();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-foreground text-sm">
        <span className="live-dot mr-2 h-1.5 w-1.5 rounded-full bg-signal-green inline-block" />
        Loading config...
      </div>
    );
  }

  if (!config) {
    return (
      <div className="glow-card rounded-lg p-8 text-center">
        <div className="text-muted-foreground text-sm">
          Consumer offline. Cannot load configuration.
        </div>
      </div>
    );
  }

  const isLive = config.trading_mode === "live";
  const rows = [
    { label: isLive ? "Balance" : "Bankroll", value: `$${config.bankroll_usdc.toFixed(2)}`, unit: "USDC" },
    { label: "Max Position", value: `$${config.max_position_usd.toFixed(2)}`, unit: "per trade" },
    { label: "Kelly Fraction", value: config.kelly_fraction.toString(), unit: "\u00D7" },
    { label: "Edge Threshold", value: `${config.edge_threshold_pct}%`, unit: "min" },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {/* Trading Config */}
      <div className="glow-card rounded-lg overflow-hidden">
        <div className="border-b border-[#1e2235] px-4 py-2 flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
            Trading Configuration
          </span>
          <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold ${
            config.trading_mode === "live"
              ? "bg-signal-red/15 text-signal-red border-signal-red/30"
              : "bg-signal-amber/15 text-signal-amber border-signal-amber/30"
          }`}>
            {config.trading_mode}
          </span>
        </div>

        <div className="p-4 space-y-0">
          {rows.map((r) => (
            <div
              key={r.label}
              className="flex items-center justify-between py-2.5 border-b border-[#1e2235]/30 last:border-0"
            >
              <span className="text-xs text-muted-foreground">{r.label}</span>
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-semibold num">{r.value}</span>
                <span className="text-[10px] text-muted-foreground/50">{r.unit}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* x402 */}
      <div className="glow-card rounded-lg overflow-hidden">
        <div className="border-b border-[#1e2235] px-4 py-2">
          <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
            x402 Signal Marketplace
          </span>
        </div>

        <div className="p-6 flex flex-col items-center justify-center min-h-[200px]">
          <div className="w-12 h-12 rounded-full border border-[#1e2235] flex items-center justify-center mb-4">
            <span className="text-lg text-muted-foreground/30">$</span>
          </div>
          <p className="text-sm text-muted-foreground text-center mb-3">
            Pay-per-signal marketplace using the x402 protocol
          </p>
          <span className="inline-flex items-center rounded-full border border-[#1e2235] px-3 py-1 text-[10px] uppercase tracking-widest text-muted-foreground/50">
            Coming Soon
          </span>
        </div>
      </div>
    </div>
  );
}
