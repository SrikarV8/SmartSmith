import {
  AgentMode,
  ChatResponse,
  Citation,
  ConversationHistoryItem,
  SourceMode,
} from "../types/chat";

/**
 * Real API client that talks to the SmartSmith FastAPI backend
 * (see ../../../server.py which wraps runtime_loop.py).
 *
 * Uses Server-Sent Events to stream tokens from the backend, then
 * receives a final JSON payload with the source mode and citations.
 *
 * The backend base URL can be configured via REACT_APP_API_URL
 * (falls back to http://localhost:8000).
 */

const API_BASE =
  (process.env.REACT_APP_API_URL as string | undefined) ||
  "http://localhost:8000";

interface RawCitation {
  title?: string;
  url: string;
  snippet?: string;
  score?: number;
  source: "vector" | "web";
}

interface FinalPayload {
  answer: string;
  agent_mode: AgentMode;
  source_mode: SourceMode;
  citations: RawCitation[];
}

function normalizeCitations(raw: RawCitation[] | undefined): Citation[] {
  if (!raw) return [];
  return raw.map((c) => ({
    title: c.title || c.url,
    url: c.url,
    snippet: c.snippet,
    score: c.score,
    source: c.source,
  }));
}

/**
 * Streams a chat response from the backend.
 *
 * The backend's /chat endpoint returns SSE where each event is one
 * of:
 *   event: token   data: "<string chunk>"
 *   event: final   data: { answer, source_mode, citations }
 *   event: error   data: { message }
 */
export async function sendChatMessage(
  query: string,
  agentMode: AgentMode,
  conversationHistory: ConversationHistoryItem[],
  onToken: (token: string) => void,
  signal?: AbortSignal
): Promise<ChatResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({
        query,
        agent_mode: agentMode,
        conversation_history: conversationHistory,
      }),
      signal,
    });
  } catch (err) {
    // Network-level failure: backend not running, wrong URL, CORS blocked,
    // DNS resolution, etc. fetch() throws a bare TypeError in these cases
    // which is not helpful by itself.
    if ((err as any)?.name === "AbortError") throw err;
    throw new Error(
      `Could not reach backend at ${API_BASE}. Is \`uvicorn server:app --port 8000\` running? (${
        (err as Error).message
      })`
    );
  }

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `Backend request failed (${res.status}): ${text || res.statusText}`
    );
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let final: FinalPayload | null = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Split on double newlines (SSE event boundaries)
    let sepIdx;
    while ((sepIdx = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, sepIdx);
      buffer = buffer.slice(sepIdx + 2);

      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of rawEvent.split("\n")) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trim());
        }
      }
      const dataStr = dataLines.join("\n");
      if (!dataStr) continue;

      if (eventName === "token") {
        // Token payload is JSON-encoded string to preserve whitespace
        try {
          const token = JSON.parse(dataStr) as string;
          onToken(token);
        } catch {
          onToken(dataStr);
        }
      } else if (eventName === "final") {
        try {
          final = JSON.parse(dataStr) as FinalPayload;
        } catch (e) {
          throw new Error("Malformed final payload from backend");
        }
      } else if (eventName === "error") {
        try {
          const err = JSON.parse(dataStr) as { message?: string };
          throw new Error(err.message || "Backend error");
        } catch {
          throw new Error(dataStr);
        }
      }
    }
  }

  if (!final) {
    throw new Error("Backend closed stream without a final payload");
  }

  return {
    answer: final.answer,
    agentMode: final.agent_mode,
    sourceMode: final.source_mode,
    citations: normalizeCitations(final.citations),
  };
}
