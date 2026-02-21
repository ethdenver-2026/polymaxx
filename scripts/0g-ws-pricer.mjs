/**
 * WebSocket server that wraps the 0G Compute Network REST API.
 *
 * The producer connects via WebSocket and sends pricing requests.
 * This server handles 0G auth and forwards to the REST chat/completions endpoint.
 *
 * Usage:
 *   ZG_PRIVATE_KEY=0x... ZG_NETWORK=mainnet node scripts/0g-ws-pricer.mjs
 *
 * Protocol:
 *   Client sends:  {"type": "price_request", "request_id": "...", "prompt": "...", "temperature": 0.8}
 *   Server sends:  {"type": "price_response", "request_id": "...", "price": 0.35, "raw": "0.35", "error": null}
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

// Cached auth state — refreshed periodically
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

async function callLLM(prompt, temperature) {
  // Refresh auth token for each request (tokens are short-lived)
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

function extractPrice(raw) {
  const match = raw.match(/\d+\.?\d*/);
  if (!match) return null;
  const price = parseFloat(match[0]);
  return Math.max(0.01, Math.min(5.0, price));
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
  const prompt = msg.prompt || "";
  const temperature = msg.temperature ?? 0.8;

  try {
    const rawResponse = await callLLM(prompt, temperature);
    const price = extractPrice(rawResponse);

    ws.send(
      JSON.stringify({
        type: "price_response",
        request_id: requestId,
        price,
        raw: rawResponse.slice(0, 500),
        error: price === null ? "no_numeric_value" : null,
      }),
    );

    console.log(
      `[${requestId}] price=$${price} temp=${temperature} raw="${rawResponse.slice(0, 80)}"`,
    );
  } catch (err) {
    ws.send(
      JSON.stringify({
        type: "price_response",
        request_id: requestId,
        price: null,
        raw: null,
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
    console.log("Producer connected");

    ws.on("message", (data) => handleMessage(ws, data.toString()));
    ws.on("close", () => console.log("Producer disconnected"));
    ws.on("error", (err) => console.error("WS error:", err.message));

    // Send ready message with model info
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
