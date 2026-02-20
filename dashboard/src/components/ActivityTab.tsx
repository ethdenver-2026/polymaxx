import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { useActivity } from "@/hooks/queries";

interface ActivityTabProps {
  wallet: string;
}

export function ActivityTab({ wallet }: ActivityTabProps) {
  const { data: activity, isLoading } = useActivity(wallet);

  if (isLoading) {
    return <p className="text-muted-foreground p-4">Loading activity...</p>;
  }

  if (!activity || activity.length === 0) {
    return <p className="text-muted-foreground p-4">No recent activity.</p>;
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead>Type</TableHead>
            <TableHead className="min-w-[200px]">Market</TableHead>
            <TableHead>Side</TableHead>
            <TableHead className="text-right">Price</TableHead>
            <TableHead className="text-right">Size</TableHead>
            <TableHead className="text-right">USDC</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {activity.map((a, i) => (
            <TableRow key={a.id || i}>
              <TableCell className="text-sm whitespace-nowrap">
                {new Date(a.timestamp).toLocaleString()}
              </TableCell>
              <TableCell>
                <Badge variant="outline">{a.type}</Badge>
              </TableCell>
              <TableCell className="max-w-[300px] truncate text-sm">
                {a.title}
              </TableCell>
              <TableCell>
                {a.side && (
                  <Badge variant={a.side === "BUY" ? "default" : "secondary"}>
                    {a.side}
                  </Badge>
                )}
              </TableCell>
              <TableCell className="text-right">
                {a.price ? `$${a.price.toFixed(3)}` : "—"}
              </TableCell>
              <TableCell className="text-right">
                {a.size ? a.size.toFixed(2) : "—"}
              </TableCell>
              <TableCell className="text-right">
                {a.usdcSize ? `$${a.usdcSize.toFixed(2)}` : "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
