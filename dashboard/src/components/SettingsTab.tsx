import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { useConfig } from "@/hooks/queries";

export function SettingsTab() {
  const { data: config, isLoading } = useConfig();

  if (isLoading) {
    return <p className="text-muted-foreground p-4">Loading config...</p>;
  }

  if (!config) {
    return (
      <p className="text-muted-foreground p-4">
        Could not load config. Is the consumer running?
      </p>
    );
  }

  const rows = [
    { label: "Bankroll", value: `$${config.bankroll_usdc.toFixed(2)} USDC` },
    { label: "Max Position", value: `$${config.max_position_usd.toFixed(2)}` },
    { label: "Kelly Fraction", value: `${config.kelly_fraction}` },
    { label: "Edge Threshold", value: `${config.edge_threshold_pct}%` },
    { label: "Daily Loss Limit", value: `${config.daily_loss_limit_pct}%` },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Trading Configuration
            <Badge
              variant={config.trading_mode === "live" ? "destructive" : "secondary"}
            >
              {config.trading_mode.toUpperCase()}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="space-y-3">
            {rows.map((r) => (
              <div key={r.label} className="flex justify-between">
                <dt className="text-muted-foreground">{r.label}</dt>
                <dd className="font-medium">{r.value}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>x402 Signal Marketplace</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-center justify-center py-8">
          <Separator className="mb-4" />
          <p className="text-muted-foreground text-center">
            Pay-per-signal marketplace using the x402 protocol.
          </p>
          <Badge variant="outline" className="mt-4">
            Coming Soon
          </Badge>
        </CardContent>
      </Card>
    </div>
  );
}
