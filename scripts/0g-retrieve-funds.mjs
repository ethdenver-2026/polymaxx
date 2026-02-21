/**
 * Retrieve funds from 0G provider sub-accounts back to the ledger.
 *
 * Usage:
 *   ZG_PRIVATE_KEY=0x... ZG_NETWORK=mainnet node scripts/0g-retrieve-funds.mjs
 */

import { ethers } from "ethers";
import { createZGComputeNetworkBroker } from "@0glabs/0g-serving-broker";

const PRIVATE_KEY = process.env.ZG_PRIVATE_KEY;
if (!PRIVATE_KEY) {
  console.error("Error: ZG_PRIVATE_KEY environment variable is required");
  process.exit(1);
}

const isMainnet = process.env.ZG_NETWORK === "mainnet";
const RPC_URL = isMainnet
  ? "https://evmrpc.0g.ai"
  : "https://evmrpc-testnet.0g.ai";

async function main() {
  console.log(`Network: ${isMainnet ? "mainnet" : "testnet"}`);

  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const wallet = new ethers.Wallet(PRIVATE_KEY, provider);
  console.log(`Wallet: ${wallet.address}`);

  const broker = await createZGComputeNetworkBroker(wallet);

  // Check ledger before
  try {
    const ledger = await broker.ledger.getLedger();
    console.log(`Ledger balance before: ${ethers.formatEther(ledger.balance ?? "0")} A0GI`);
  } catch {
    console.log("No ledger found");
  }

  // Retrieve funds from all inference provider sub-accounts
  console.log("Retrieving funds from inference sub-accounts...");
  try {
    await broker.ledger.retrieveFund("inference");
    console.log("Retrieve complete!");
  } catch (e) {
    console.error("Retrieve failed:", e.message?.split("\n")[0] || e);
  }

  // Check ledger after
  try {
    const ledger = await broker.ledger.getLedger();
    console.log(`Ledger balance after: ${ethers.formatEther(ledger.balance ?? "0")} A0GI`);
  } catch {
    console.log("Could not read ledger");
  }
}

main().catch((err) => {
  console.error("Fatal:", err.message || err);
  process.exit(1);
});
