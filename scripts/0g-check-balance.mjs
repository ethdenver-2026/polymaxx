/**
 * Check full 0G ledger state and optionally refund to wallet.
 *
 * Usage:
 *   ZG_PRIVATE_KEY=0x... ZG_NETWORK=mainnet node scripts/0g-check-balance.mjs
 *   ZG_PRIVATE_KEY=0x... ZG_NETWORK=mainnet ZG_REFUND=1.0 node scripts/0g-check-balance.mjs
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

const refundAmount = process.env.ZG_REFUND ? parseFloat(process.env.ZG_REFUND) : null;

async function main() {
  console.log(`Network: ${isMainnet ? "mainnet" : "testnet"}\n`);

  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const wallet = new ethers.Wallet(PRIVATE_KEY, provider);
  const walletBal = await provider.getBalance(wallet.address);
  console.log(`Wallet: ${wallet.address}`);
  console.log(`Wallet balance: ${ethers.formatEther(walletBal)} A0GI\n`);

  const broker = await createZGComputeNetworkBroker(wallet);

  // Get ledger
  try {
    const ledger = await broker.ledger.getLedger();
    console.log("=== Ledger ===");
    console.log(`  Total balance:     ${ethers.formatEther(ledger.totalBalance ?? "0")} A0GI`);
    console.log(`  Available balance: ${ethers.formatEther(ledger.availableBalance ?? "0")} A0GI`);
    console.log(`  Raw:`, JSON.stringify(ledger, (_, v) => typeof v === 'bigint' ? v.toString() : v));
  } catch (e) {
    console.log("No ledger found:", e.message?.split("\n")[0] || e);
  }

  // Refund from ledger back to wallet
  if (refundAmount) {
    console.log(`\nRefunding ${refundAmount} A0GI from ledger to wallet...`);
    try {
      await broker.ledger.refund(refundAmount);
      console.log("Refund complete!");
      const newBal = await provider.getBalance(wallet.address);
      console.log(`New wallet balance: ${ethers.formatEther(newBal)} A0GI`);
    } catch (e) {
      console.log("Refund failed:", e.message?.split("\n")[0] || e);
    }
  }
}

main().catch((err) => {
  console.error("Fatal:", err.message || err);
  process.exit(1);
});
