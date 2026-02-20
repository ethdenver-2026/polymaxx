import { useQuery } from "@tanstack/react-query";
import { getPositions, getPortfolioValue, getActivity } from "@/api/polymarket";
import { getBalances, getSignalLog, getConfig } from "@/api/consumer";

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
