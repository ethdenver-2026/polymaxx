import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getPositions, getPortfolioValue, getActivity } from "@/api/polymarket";
import { getAuctions, getBalances, getSignalLog, getConfig, generateSignal, setTradingMode, getPaperPositions } from "@/api/consumer";

export function useConfig() {
  return useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
    staleTime: 60_000,
  });
}

export function usePositions(wallet: string | undefined) {
  return useQuery({
    queryKey: ["positions", wallet],
    queryFn: () => getPositions(wallet!),
    enabled: !!wallet,
    refetchInterval: 10_000,
  });
}

export function usePortfolioValue(wallet: string | undefined) {
  return useQuery({
    queryKey: ["portfolioValue", wallet],
    queryFn: () => getPortfolioValue(wallet!),
    enabled: !!wallet,
    refetchInterval: 30_000,
  });
}

export function useBalances() {
  return useQuery({
    queryKey: ["balances"],
    queryFn: getBalances,
    refetchInterval: 30_000,
  });
}

export function useSignals() {
  return useQuery({
    queryKey: ["signals"],
    queryFn: getSignalLog,
    refetchInterval: 5_000,
  });
}

export function useActivity(wallet: string | undefined) {
  return useQuery({
    queryKey: ["activity", wallet],
    queryFn: () => getActivity(wallet!),
    enabled: !!wallet,
    refetchInterval: 15_000,
  });
}

export function useGenerateSignal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (cities?: string[]) => generateSignal(cities),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["signals"] });
      qc.invalidateQueries({ queryKey: ["paperPositions"] });
    },
  });
}

export function useSetTradingMode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mode: string) => setTradingMode(mode),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["config"] });
      qc.invalidateQueries({ queryKey: ["signals"] });
    },
  });
}

export function useAuctions() {
  return useQuery({
    queryKey: ["auctions"],
    queryFn: getAuctions,
    refetchInterval: 5_000,
  });
}


export function usePaperPositions(enabled: boolean) {
  return useQuery({
    queryKey: ["paperPositions"],
    queryFn: getPaperPositions,
    enabled,
    refetchInterval: 10_000,
  });
}
