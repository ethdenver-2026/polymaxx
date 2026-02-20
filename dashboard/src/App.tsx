import { useQuery } from "@tanstack/react-query";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Header } from "@/components/Header";
import { PortfolioTab } from "@/components/PortfolioTab";
import { PositionsTab } from "@/components/PositionsTab";
import { SignalsTab } from "@/components/SignalsTab";
import { ActivityTab } from "@/components/ActivityTab";
import { SettingsTab } from "@/components/SettingsTab";
import { getConfig, getHealth } from "@/api/consumer";

function App() {
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
      <main className="mx-auto max-w-7xl px-6 py-6">
        <Tabs defaultValue="portfolio">
          <TabsList className="mb-6">
            <TabsTrigger value="portfolio">Portfolio</TabsTrigger>
            <TabsTrigger value="positions">Positions</TabsTrigger>
            <TabsTrigger value="signals">Signals</TabsTrigger>
            <TabsTrigger value="activity">Activity</TabsTrigger>
            <TabsTrigger value="settings">Settings</TabsTrigger>
          </TabsList>

          <TabsContent value="portfolio">
            {wallet ? (
              <PortfolioTab wallet={wallet} />
            ) : (
              <p className="text-muted-foreground">
                Waiting for consumer config (wallet address)...
              </p>
            )}
          </TabsContent>

          <TabsContent value="positions">
            {wallet ? (
              <PositionsTab wallet={wallet} />
            ) : (
              <p className="text-muted-foreground">
                Waiting for wallet address...
              </p>
            )}
          </TabsContent>

          <TabsContent value="signals">
            <SignalsTab />
          </TabsContent>

          <TabsContent value="activity">
            {wallet ? (
              <ActivityTab wallet={wallet} />
            ) : (
              <p className="text-muted-foreground">
                Waiting for wallet address...
              </p>
            )}
          </TabsContent>

          <TabsContent value="settings">
            <SettingsTab />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}

export default App;
