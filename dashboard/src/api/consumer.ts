import type { Balances, ConsumerSignal, ConsumerConfig, GenerateSignalResponse, PaperPosition } from "./types";

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

export async function generateSignal(cities?: string[]): Promise<GenerateSignalResponse> {
  const res = await fetch("/api/generate-signal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cities ? { cities } : {}),
  });
  return res.json();
}

export async function setTradingMode(mode: string): Promise<{ ok: boolean; trading_mode?: string; error?: string }> {
  const res = await fetch("/api/config/trading-mode", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  return res.json();
}

export async function getPaperPositions(): Promise<PaperPosition[]> {
  const res = await fetch("/api/paper-positions");
  return res.json();
}
