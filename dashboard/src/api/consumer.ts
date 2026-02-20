import type { Balances, ConsumerSignal, ConsumerConfig } from "./types";

export async function getBalances(): Promise<Balances> {
  const res = await fetch("/api/balances");
  return res.json();
}

export async function getSignalLog(): Promise<ConsumerSignal[]> {
  const res = await fetch("/api/signals?limit=200");
  return res.json();
}

export async function getConfig(): Promise<ConsumerConfig> {
  const res = await fetch("/api/config");
  return res.json();
}

export async function getHealth(): Promise<{ status: string }> {
  const res = await fetch("/api/health");
  return res.json();
}
