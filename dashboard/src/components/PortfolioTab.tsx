import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { useBalances, usePortfolioValue, useSignals } from "@/hooks/queries";
import { DollarSign, TrendingUp, Wallet, Coins } from "lucide-react";

interface PortfolioTabProps {
  wallet: string;
}

function StatCard({
  title,
  value,
  icon: Icon,
  subtitle,
}: {
  title: string;
  value: string;
  icon: React.ComponentType<{ className?: string }>;
  subtitle?: string;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        {subtitle && (
          <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>
        )}
      </CardContent>
    </Card>
  );
}

export function PortfolioTab({ wallet }: PortfolioTabProps) {
  const { data: balances, isLoading: balLoading } = useBalances();
  const { data: portfolio, isLoading: portLoading } = usePortfolioValue(wallet);
  const { data: signals } = useSignals();

  const executed = signals?.filter((s) => s.action === "executed") ?? [];
  const totalSignals = signals?.length ?? 0;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="CLOB Balance (Free Cash)"
          value={
            balLoading
              ? "..."
              : balances?.error
                ? "Error"
                : `$${(balances?.polymarket_usdc ?? 0).toFixed(2)}`
          }
          icon={DollarSign}
          subtitle="Polymarket USDC.e"
        />
        <StatCard
          title="Portfolio Value"
          value={
            portLoading
              ? "..."
              : `$${(portfolio?.portfolioValue ?? 0).toFixed(2)}`
          }
          icon={Wallet}
          subtitle="Positions + cash"
        />
        <StatCard
          title="P&L"
          value={
            portLoading
              ? "..."
              : `$${(portfolio?.pnl ?? 0).toFixed(2)}`
          }
          icon={TrendingUp}
          subtitle={
            portfolio?.percentPnl != null
              ? `${(portfolio.percentPnl * 100).toFixed(1)}%`
              : undefined
          }
        />
        <StatCard
          title="On-chain POL"
          value={
            balLoading
              ? "..."
              : `${(balances?.onchain_pol ?? 0).toFixed(4)}`
          }
          icon={Coins}
          subtitle={
            balances
              ? `On-chain USDC: $${(balances.onchain_usdc ?? 0).toFixed(2)}`
              : undefined
          }
        />
      </div>

      <Separator />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Total Signals
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalSignals}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Executed Trades
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{executed.length}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Execution Rate
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {totalSignals > 0
                ? `${((executed.length / totalSignals) * 100).toFixed(0)}%`
                : "N/A"}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
