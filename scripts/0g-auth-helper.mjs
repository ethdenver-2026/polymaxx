/**
 * Thin Node.js script that initializes the 0G broker, gets auth headers,
 * and prints them as JSON. Called by Python llm_pricer via subprocess.
 *
 * Skips balance validation — generates the auth token directly.
 *
 * Usage:
 *   ZG_PRIVATE_KEY=0x... ZG_NETWORK=mainnet node scripts/0g-auth-helper.mjs
 *
 * Output (stdout):
 *   {"endpoint": "https://...", "model": "...", "headers": {"Authorization": "Bearer ..."}}
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

const providerIndex = parseInt(process.env.ZG_PROVIDER_INDEX ?? "0", 10);

async function main() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const wallet = new ethers.Wallet(PRIVATE_KEY, provider);
  const broker = await createZGComputeNetworkBroker(wallet);

  // Discover chatbot services
  const services = await broker.inference.listService();
  const chatbotServices = services.filter((s) => s.serviceType === "chatbot");

  if (chatbotServices.length === 0) {
    console.error("No chatbot services available");
    process.exit(1);
  }

  const service = chatbotServices[providerIndex] || chatbotServices[0];
  const providerAddress = service.provider;

  // Get endpoint + model metadata
  const { endpoint, model } = await broker.inference.getServiceMetadata(providerAddress);

  // Generate auth headers directly via the internal requestProcessor
  // This skips topUpAccountIfNeeded (balance validation) and just signs the token
  const headers = await broker.inference.requestProcessor.getHeader(providerAddress);

  // Output as JSON for Python to consume
  const output = { endpoint, model, headers };
  console.log(JSON.stringify(output));
}

main().catch((err) => {
  console.error("Fatal error:", err.message || err);
  process.exit(1);
});
