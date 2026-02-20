import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { useSignals } from "@/hooks/queries";

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString();
}

function pct(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function ActionBadge({ action }: { action: string }) {
  switch (action) {
    case "executed":
      return <Badge className="bg-green-600">Executed</Badge>;
    case "skipped":
      return <Badge variant="secondary">Skipped</Badge>;
    case "error":
      return <Badge variant="destructive">Error</Badge>;
    default:
      return <Badge variant="outline">{action}</Badge>;
  }
}

export function SignalsTab() {
  const { data: signals, isLoading } = useSignals();

  if (isLoading) {
    return <p className="text-muted-foreground p-4">Loading signals...</p>;
  }

  if (!signals || signals.length === 0) {
    return (
      <p className="text-muted-foreground p-4">
        No signals received yet. Start the producer to generate signals.
      </p>
    );
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead className="min-w-[200px]">Description</TableHead>
            <TableHead className="text-right">Model Prob</TableHead>
            <TableHead className="text-right">Signal Price</TableHead>
            <TableHead className="text-right">Live Price</TableHead>
            <TableHead className="text-right">Signal Edge</TableHead>
            <TableHead className="text-right">Live Edge</TableHead>
            <TableHead>Action</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {signals.map((s) => (
            <TableRow key={s.id}>
              <TableCell className="text-sm whitespace-nowrap">
                {formatTime(s.received_at)}
              </TableCell>
              <TableCell className="max-w-[300px] truncate text-sm">
                {s.description || s.token_id.slice(0, 16) + "..."}
              </TableCell>
              <TableCell className="text-right">
                {pct(s.model_probability)}
              </TableCell>
              <TableCell className="text-right">
                {s.signal_price !== null ? `$${s.signal_price.toFixed(3)}` : "—"}
              </TableCell>
              <TableCell className="text-right">
                {s.live_price !== null ? `$${s.live_price.toFixed(3)}` : "—"}
              </TableCell>
              <TableCell className="text-right">{pct(s.signal_edge)}</TableCell>
              <TableCell className="text-right">{pct(s.live_edge)}</TableCell>
              <TableCell>
                <ActionBadge action={s.action} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
