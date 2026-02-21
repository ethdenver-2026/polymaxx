/**
 * WebSocket server that wraps the 0G Compute Network REST API.
 *
 * Clients connect via WebSocket and send pricing requests with signal preview data.
 * The LLM determines a bid_amount and the server returns a structured AuctionBidMessage.
 *
 * Usage:
 *   ZG_PRIVATE_KEY=0x... ZG_NETWORK=mainnet node scripts/0g-ws-pricer.mjs
 *
 * Protocol:
 *   Client sends:
 *     {
 *       "type": "price_request",
 *       "request_id": "uuid",
 *       "auction_id": "...",
 *       "consumer_did": "...",
 *       "wallet_address": "0x...",
 *       "preview": { signal_type, producer_did, edge, confidence, last_price_paid, auction_end_utc },
 *       "temperature": 0.85
 *     }
 *
 *   Server sends:
 *     {
 *       "type": "price_response",
 *       "request_id": "uuid",
 *       "bid": { "type": "AuctionBidMessage", "version": 1, "auction_id", "consumer_did", "wallet_address", "bid_amount" },
 *       "error": null
 *     }
 */

import { WebSocketServer } from "ws";
import { ethers } from "ethers";
import { createZGComputeNetworkBroker } from "@0glabs/0g-serving-broker";

const PORT = parseInt(process.env.ZG_WS_PORT ?? "8089", 10);
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

const MIN_BID = 0.01;
const MAX_BID = 5.0;

// Cached auth state
let cachedEndpoint = "";
let cachedModel = "";
let cachedHeaders = {};
let broker = null;
let providerAddress = "";

async function initBroker() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const wallet = new ethers.Wallet(PRIVATE_KEY, provider);
  broker = await createZGComputeNetworkBroker(wallet);

  const services = await broker.inference.listService();
  const chatbotServices = services.filter((s) => s.serviceType === "chatbot");
  if (chatbotServices.length === 0) {
    throw new Error("No chatbot services available on 0G network");
  }

  const service = chatbotServices[providerIndex] || chatbotServices[0];
  providerAddress = service.provider;

  const { endpoint, model } =
    await broker.inference.getServiceMetadata(providerAddress);
  cachedEndpoint = endpoint;
  cachedModel = model;

  console.log(`0G service: ${cachedModel} @ ${cachedEndpoint}`);
}

async function refreshAuth() {
  cachedHeaders =
    await broker.inference.requestProcessor.getHeader(providerAddress);
}

function buildPrompt(preview) {
  const edge = preview.edge ?? 0;
  const confidence = preview.confidence ?? 0;
  const lastPaid = preview.last_price_paid ?? 0;

  return [
    "You are a pricing engine for a prediction-market signal marketplace.",
    "A producer is auctioning a trading signal. You must decide how much to bid.",
    "",
    "Signal preview:",
    `- Producer: ${preview.producer_did ?? "unknown"}`,
    `- Signal type: ${preview.signal_type ?? "weather"}`,
    `- Edge (model vs market): ${Number(edge).toFixed(4)}`,
    `- Model confidence: ${Number(confidence).toFixed(2)}`,
    `- Last price paid for a signal: $${Number(lastPaid).toFixed(2)}`,
    `- Auction ends: ${preview.auction_end_utc ?? "unknown"}`,
    "",
    "Price factors:",
    "- Higher edge = more valuable signal (bigger mispricing found)",
    "- Higher confidence = more reliable (tighter ensemble spread)",
    "- Last price paid anchors expectations",
    "- Producer reputation matters but is hard to quantify early on",
    "",
    `Respond with ONLY a JSON object in this exact format (bid_amount between ${MIN_BID} and ${MAX_BID}):`,
    '{"bid_amount": <number>}',
  ].join("\n");
}

async function callLLM(prompt, temperature) {
  await refreshAuth();

  const resp = await fetch(`${cachedEndpoint}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...cachedHeaders },
    body: JSON.stringify({
      model: cachedModel,
      messages: [{ role: "user", content: prompt }],
      temperature,
      max_tokens: 4096,
    }),
  });

  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`0G API error ${resp.status}: ${body.slice(0, 200)}`);
  }

  const data = await resp.json();
  const message = data.choices?.[0]?.message;
  const content = message?.content || "";
  const reasoning = message?.reasoning_content || "";
  return content.trim() || reasoning.trim();
}

function extractBidAmount(raw) {
  // Try to parse as JSON first
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed.bid_amount === "number") {
      return Math.max(MIN_BID, Math.min(MAX_BID, parsed.bid_amount));
    }
  } catch {
    // Not valid JSON — fall through to regex
  }

  // Find JSON object in the response
  const jsonMatch = raw.match(/\{[^}]*"bid_amount"\s*:\s*([\d.]+)[^}]*\}/);
  if (jsonMatch) {
    const amount = parseFloat(jsonMatch[1]);
    if (!isNaN(amount)) return Math.max(MIN_BID, Math.min(MAX_BID, amount));
  }

  // Last resort: extract first number
  const numMatch = raw.match(/\d+\.?\d*/);
  if (numMatch) {
    const amount = parseFloat(numMatch[0]);
    return Math.max(MIN_BID, Math.min(MAX_BID, amount));
  }

  return null;
}

async function handleMessage(ws, raw) {
  let msg;
  try {
    msg = JSON.parse(raw);
  } catch {
    ws.send(JSON.stringify({ type: "error", error: "Invalid JSON" }));
    return;
  }

  if (msg.type !== "price_request") {
    ws.send(
      JSON.stringify({ type: "error", error: `Unknown type: ${msg.type}` }),
    );
    return;
  }

  const requestId = msg.request_id || "";
  const auctionId = msg.auction_id || "";
  const consumerDid = msg.consumer_did || "";
  const walletAddress = msg.wallet_address || "";
  const preview = msg.preview || {};
  const temperature = msg.temperature ?? 0.8;

  try {
    const prompt = buildPrompt(preview);
    const rawResponse = await callLLM(prompt, temperature);
    const bidAmount = extractBidAmount(rawResponse);

    if (bidAmount === null) {
      ws.send(
        JSON.stringify({
          type: "price_response",
          request_id: requestId,
          bid: null,
          error: "no_bid_amount_extracted",
          raw: rawResponse.slice(0, 500),
        }),
      );
      return;
    }

    const bid = {
      type: "AuctionBidMessage",
      version: 1,
      auction_id: auctionId,
      consumer_did: consumerDid,
      wallet_address: walletAddress,
      bid_amount: bidAmount,
    };

    ws.send(
      JSON.stringify({
        type: "price_response",
        request_id: requestId,
        bid,
        error: null,
      }),
    );

    console.log(
      `[${requestId}] bid=$${bidAmount} auction=${auctionId} raw="${rawResponse.slice(0, 80)}"`,
    );
  } catch (err) {
    ws.send(
      JSON.stringify({
        type: "price_response",
        request_id: requestId,
        bid: null,
        error: err.message || String(err),
      }),
    );
    console.error(`[${requestId}] error: ${err.message}`);
  }
}

async function main() {
  console.log("Initializing 0G broker...");
  await initBroker();

  const wss = new WebSocketServer({ port: PORT });

  wss.on("connection", (ws) => {
    console.log("Client connected");

    ws.on("message", (data) => handleMessage(ws, data.toString()));
    ws.on("close", () => console.log("Client disconnected"));
    ws.on("error", (err) => console.error("WS error:", err.message));

    ws.send(
      JSON.stringify({
        type: "ready",
        endpoint: cachedEndpoint,
        model: cachedModel,
      }),
    );
  });

  console.log(`0G WS pricer listening on ws://localhost:${PORT}`);
}

main().catch((err) => {
  console.error("Fatal:", err.message || err);
  process.exit(1);
});
