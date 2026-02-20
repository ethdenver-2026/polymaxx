import { Activity, CircleDot } from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface HeaderProps {
  walletAddress: string;
  consumerConnected: boolean;
}

export function Header({ walletAddress, consumerConnected }: HeaderProps) {
  const shortAddr = walletAddress
    ? `${walletAddress.slice(0, 6)}...${walletAddress.slice(-4)}`
    : "Not connected";

  return (
    <header className="flex items-center justify-between border-b px-6 py-4">
      <div className="flex items-center gap-3">
        <Activity className="h-6 w-6 text-primary" />
        <h1 className="text-xl font-semibold">Signal Market</h1>
      </div>
      <div className="flex items-center gap-3">
        <Badge variant={consumerConnected ? "default" : "destructive"} className="gap-1.5">
          <CircleDot className="h-3 w-3" />
          {consumerConnected ? "Consumer Online" : "Consumer Offline"}
        </Badge>
        <code className="rounded bg-muted px-2 py-1 text-sm font-mono">
          {shortAddr}
        </code>
      </div>
    </header>
  );
}
