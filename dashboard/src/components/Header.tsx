

interface HeaderProps {
  walletAddress: string;
  consumerConnected: boolean;
}

export function Header({ walletAddress, consumerConnected }: HeaderProps) {
  const shortAddr = walletAddress
    ? `${walletAddress.slice(0, 6)}...${walletAddress.slice(-4)}`
    : "----";

  return (
    <header className="scanline border-b border-[#1e2235] bg-[#0a0c12]/80 backdrop-blur-sm">
      <div className="mx-auto max-w-7xl flex items-center justify-between px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="relative">
            <img src="/polymaxxlogo.png" alt="Polymaxx" className="h-6 w-6" />
            {consumerConnected && (
              <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-signal-green live-dot" />
            )}
          </div>
          <h1
            className="text-lg font-bold tracking-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            POLYMAXX
          </h1>
          <span className="text-[10px] text-muted-foreground tracking-widest uppercase ml-1">
            v0.1
          </span>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                consumerConnected ? "bg-signal-green live-dot" : "bg-signal-red"
              }`}
            />
            <span className="text-xs text-muted-foreground uppercase tracking-wider">
              {consumerConnected ? "Live" : "Offline"}
            </span>
          </div>

          <div className="h-4 w-px bg-[#1e2235]" />

          <code className="text-xs text-muted-foreground tracking-wider">
            {shortAddr}
          </code>
        </div>
      </div>
    </header>
  );
}
