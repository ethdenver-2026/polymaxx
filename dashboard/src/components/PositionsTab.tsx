import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { usePositions } from "@/hooks/queries";

interface PositionsTabProps {
  wallet: string;
}

export function PositionsTab({ wallet }: PositionsTabProps) {
  const { data: positions, isLoading } = usePositions(wallet);

  if (isLoading) {
    return <p className="text-muted-foreground p-4">Loading positions...</p>;
  }

  if (!positions || positions.length === 0) {
    return (
      <p className="text-muted-foreground p-4">No open positions found.</p>
    );
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="min-w-[200px]">Market</TableHead>
            <TableHead>Outcome</TableHead>
            <TableHead className="text-right">Size</TableHead>
            <TableHead className="text-right">Avg Price</TableHead>
            <TableHead className="text-right">Cur Price</TableHead>
            <TableHead className="text-right">Value</TableHead>
            <TableHead className="text-right">P&L ($)</TableHead>
            <TableHead className="text-right">P&L (%)</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {positions.map((p, i) => {
            const cashPnl = p.cashPnl ?? 0;
            const pnlColor =
              cashPnl > 0
                ? "text-green-600"
                : cashPnl < 0
                  ? "text-red-600"
                  : "";
            return (
              <TableRow key={`${p.conditionId ?? i}-${p.outcome}-${i}`}>
                <TableCell className="font-medium max-w-[300px] truncate">
                  {p.title ?? "—"}
                </TableCell>
                <TableCell>
                  <Badge variant={p.outcome === "Yes" ? "default" : "secondary"}>
                    {p.outcome ?? "—"}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">{(p.size ?? 0).toFixed(2)}</TableCell>
                <TableCell className="text-right">
                  ${(p.avgPrice ?? 0).toFixed(3)}
                </TableCell>
                <TableCell className="text-right">
                  ${(p.curPrice ?? 0).toFixed(3)}
                </TableCell>
                <TableCell className="text-right">
                  ${(p.currentValue ?? 0).toFixed(2)}
                </TableCell>
                <TableCell className={`text-right font-medium ${pnlColor}`}>
                  {cashPnl >= 0 ? "+" : ""}${cashPnl.toFixed(2)}
                </TableCell>
                <TableCell className={`text-right ${pnlColor}`}>
                  {((p.percentPnl ?? 0) * 100).toFixed(1)}%
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
