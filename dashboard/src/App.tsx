import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Header } from "@/components/Header";
import { PortfolioTab } from "@/components/PortfolioTab";
import { PositionsTab } from "@/components/PositionsTab";
import { SignalsTab } from "@/components/SignalsTab";
import { AuctionsTab } from "@/components/AuctionsTab";
import { ActivityTab } from "@/components/ActivityTab";
import { SettingsTab } from "@/components/SettingsTab";
import { getConfig, getHealth } from "@/api/consumer";
import { useSignalStream } from "@/hooks/useSignalStream";

const TABS = [
  { id: "portfolio", label: "Portfolio" },
  { id: "positions", label: "Positions" },
  { id: "signals", label: "Signals" },
  { id: "auctions", label: "Auctions" },
  { id: "activity", label: "Activity" },
  { id: "settings", label: "Settings" },
] as const;

type TabId = (typeof TABS)[number]["id"];

function App() {
  useSignalStream();
  const [activeTab, setActiveTab] = useState<TabId>("portfolio");

  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
    staleTime: 60_000,
    retry: 3,
  });

  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 10_000,
    retry: false,
  });

  const wallet = config?.wallet_address ?? "";
  const consumerConnected = health?.status === "ok";

  return (
    <div className="min-h-screen bg-background">
      <Header walletAddress={wallet} consumerConnected={consumerConnected} />

      <main className="mx-auto max-w-7xl px-6 py-5">
        {/* Tab bar */}
        <nav className="flex items-center gap-1 mb-6 border-b border-[#1e2235] pb-px">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`
                relative px-4 py-2 text-xs uppercase tracking-widest font-medium
                transition-colors duration-200
                ${
                  activeTab === tab.id
                    ? "text-signal-green"
                    : "text-muted-foreground hover:text-foreground"
                }
              `}
            >
              {tab.label}
              {activeTab === tab.id && (
                <span className="absolute bottom-0 left-0 right-0 h-px bg-signal-green shadow-[0_0_8px_0_#4ade8060]" />
              )}
            </button>
          ))}
        </nav>

        {/* Content */}
        <div>
          {activeTab === "portfolio" &&
            (wallet ? (
              <PortfolioTab wallet={wallet} />
            ) : (
              <WaitingState msg="Waiting for consumer config..." />
            ))}

          {activeTab === "positions" &&
            (wallet ? (
              <PositionsTab wallet={wallet} />
            ) : (
              <WaitingState msg="Waiting for wallet address..." />
            ))}

          {activeTab === "signals" && <SignalsTab />}

          {activeTab === "auctions" && <AuctionsTab />}

          {activeTab === "activity" &&
            (wallet ? (
              <ActivityTab wallet={wallet} />
            ) : (
              <WaitingState msg="Waiting for wallet address..." />
            ))}

          {activeTab === "settings" && <SettingsTab />}
        </div>
      </main>
    </div>
  );
}

function WaitingState({ msg }: { msg: string }) {
  return (
    <div className="glow-card rounded-lg p-8 text-center">
      <span className="live-dot mr-2 h-1.5 w-1.5 rounded-full bg-signal-amber inline-block" />
      <span className="text-sm text-muted-foreground">{msg}</span>
    </div>
  );
}

export default App;
