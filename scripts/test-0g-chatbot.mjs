/**
 * Test script for 0G Compute Network chatbot inference.
 *
 * Usage:
 *   ZG_PRIVATE_KEY=0x... node scripts/test-0g-chatbot.mjs
 *   ZG_PRIVATE_KEY=0x... node scripts/test-0g-chatbot.mjs "What is the weather like today?"
 *
 * Environment:
 *   ZG_PRIVATE_KEY  - EVM wallet private key with 0G tokens (required)
 *   ZG_NETWORK      - "testnet" (default) or "mainnet"
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
const userMessage = process.argv[2] || "Hello! What model are you?";

async function main() {
  console.log(`Network: ${isMainnet ? "mainnet" : "testnet"}`);
  console.log(`RPC: ${RPC_URL}\n`);

  // 1. Initialize provider + wallet + broker
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const wallet = new ethers.Wallet(PRIVATE_KEY, provider);
  const walletBal = await provider.getBalance(wallet.address);
  console.log(`Wallet: ${wallet.address}`);
  console.log(`Wallet balance: ${ethers.formatEther(walletBal)} A0GI`);

  console.log("Initializing broker...");
  const broker = await createZGComputeNetworkBroker(wallet);

  // 2. Discover chatbot services
  console.log("Listing available services...\n");
  const services = await broker.inference.listService();
  const chatbotServices = services.filter((s) => s.serviceType === "chatbot");

  if (chatbotServices.length === 0) {
    console.error("No chatbot services available on this network");
    process.exit(1);
  }

  console.log(`Found ${chatbotServices.length} chatbot service(s):`);
  for (const svc of chatbotServices) {
    console.log(`  - Provider: ${svc.provider}`);
    console.log(`    Model: ${svc.model}, URL: ${svc.url}`);
  }

  // 3. Pick service by index (ZG_PROVIDER_INDEX env, default 0)
  const service = chatbotServices[providerIndex] || chatbotServices[0];
  console.log(`\nSelected index: ${providerIndex}`);
  const providerAddress = service.provider;
  console.log(`\nUsing provider: ${providerAddress}`);

  // 4. Check ledger balance
  let ledgerBal = 0n;
  try {
    const ledger = await broker.ledger.getLedger();
    ledgerBal = BigInt(ledger.balance ?? "0");
    console.log(`Ledger balance: ${ethers.formatEther(ledgerBal)} A0GI`);
  } catch {
    console.log("No ledger found");
  }

  // Deposit if ledger is empty — mainnet requires minimum 3 A0GI
  const minDeposit = isMainnet ? 3.0 : 0.1;
  if (ledgerBal === 0n && walletBal > ethers.parseEther(String(minDeposit + 0.5))) {
    console.log(`Depositing ${minDeposit} A0GI to ledger...`);
    await broker.ledger.depositFund(minDeposit);
    ledgerBal = ethers.parseEther(String(minDeposit));
    console.log("Deposited");
  }

  // Check available balance (may differ from total due to pending retrieval)
  try {
    const fullLedger = await broker.ledger.getLedger();
    const available = BigInt(fullLedger.availableBalance ?? "0");
    console.log(`Available in ledger: ${ethers.formatEther(available)} A0GI`);
    if (available > 0n && available !== ledgerBal) {
      ledgerBal = available;
    }
  } catch { /* ignore */ }

  // 5. Acknowledge provider signer
  try {
    await broker.inference.acknowledgeProviderSigner(providerAddress);
    console.log("Provider acknowledged");
  } catch (e) {
    const msg = e.message?.split("\n")[0] || String(e);
    console.log(`Provider acknowledge: ${msg}`);
  }

  // 6. Transfer available funds to provider sub-account
  if (ledgerBal > 0n) {
    console.log(`Transferring ${ethers.formatEther(ledgerBal)} A0GI to provider sub-account...`);
    try {
      await broker.ledger.transferFund(providerAddress, "inference", ledgerBal);
      console.log("Transfer complete");
    } catch (e) {
      const msg = e.message?.split("\n")[0] || String(e);
      console.log(`Transfer failed: ${msg}`);
      console.log("Continuing anyway — sub-account may already have funds...");
    }
  }

  // 7. Get service metadata
  const { endpoint, model } = await broker.inference.getServiceMetadata(providerAddress);
  console.log(`Endpoint: ${endpoint}`);
  console.log(`Model: ${model}\n`);

  // 8. Generate auth headers
  const headers = await broker.inference.getRequestHeaders(providerAddress);

  // 9. Make the chat completion request
  const messages = [{ role: "user", content: userMessage }];
  console.log(`User: ${userMessage}`);
  console.log("---");

  const response = await fetch(`${endpoint}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({ messages, model }),
  });

  if (!response.ok) {
    const text = await response.text();
    console.error(`Request failed (${response.status}): ${text}`);
    process.exit(1);
  }

  const data = await response.json();
  const answer = data.choices?.[0]?.message?.content ?? "(no content)";
  console.log(`Assistant: ${answer}\n`);

  // 10. Process response for fee management
  if (data.usage) {
    console.log(`Usage: ${JSON.stringify(data.usage)}`);
    let chatID =
      response.headers.get("ZG-Res-Key") ||
      response.headers.get("zg-res-key") ||
      data.id;
    await broker.inference.processResponse(
      providerAddress,
      chatID || undefined,
      JSON.stringify(data.usage)
    );
    console.log("Response processed (fees settled)");
  }

  console.log("\nDone!");
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
