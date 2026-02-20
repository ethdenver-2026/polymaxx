import type { Position, Activity, PortfolioSummary } from "./types";

const DATA_API = "https://data-api.polymarket.com";

export async function getPositions(wallet: string): Promise<Position[]> {
  const res = await fetch(
    `${DATA_API}/positions?user=${wallet}&sizeThreshold=0.1&limit=50`
  );
  if (!res.ok) return [];
  const data = await res.json();
  // The API returns positions grouped by market; flatten
  if (Array.isArray(data)) return data;
  return data?.positions ?? [];
}

export async function getPortfolioValue(
  wallet: string
): Promise<PortfolioSummary | null> {
  const res = await fetch(`${DATA_API}/value?user=${wallet}`);
  if (!res.ok) return null;
  return res.json();
}

export async function getActivity(wallet: string): Promise<Activity[]> {
  const res = await fetch(
    `${DATA_API}/activity?user=${wallet}&limit=50`
  );
  if (!res.ok) return [];
  const data = await res.json();
  if (Array.isArray(data)) return data;
  return data?.activity ?? data?.history ?? [];
}
