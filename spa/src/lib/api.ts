// API client for agent-seal REST API v1
// All fetches are relative — works behind the same origin or Vite proxy.

export interface StatsResponse {
  total_events: number;
  sessions: number;
  event_types: Record<string, number>;
  integrity: "ok" | "broken" | "unknown";
  agents: string[];
}

export interface EventRecord {
  event_id: string;
  session_id: string;
  sequence: number;
  timestamp: number;
  event_type: string;
  agent_id: string;
  prompt_version: string;
  input_snapshot?: string;
  output_snapshot?: string;
  metadata?: Record<string, unknown>;
  prev_hash: string;
  hash: string;
}

export interface SessionSummary {
  session_id: string;
  event_count: number;
  last_event_type: string;
  last_timestamp: number;
  agent_id: string;
  integrity: "ok" | "broken" | "unknown";
}

export interface SessionDetail {
  session_id: string;
  event_count: number;
  integrity: "ok" | "broken" | "unknown";
  events: EventRecord[];
}

export interface VerifyResponse {
  integrity: "ok" | "broken";
  sessions?: Record<string, "ok" | "broken" | "unknown">;
  session_id?: string;
}

export interface HealthResponse {
  status: string;
  version: string;
}

// ── Fetchers ──────────────────────────────────────────────────────

export async function fetchStats(): Promise<StatsResponse> {
  const r = await fetch("/api/v1/stats");
  if (!r.ok) throw new Error(`Stats failed: ${r.status}`);
  return r.json();
}

export async function fetchEvents(params?: {
  session_id?: string;
  event_type?: string;
  limit?: number;
  offset?: number;
}): Promise<{ events: EventRecord[]; total: number; limit: number; offset: number }> {
  const qs = new URLSearchParams();
  if (params?.session_id) qs.set("session_id", params.session_id);
  if (params?.event_type) qs.set("event_type", params.event_type);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const url = "/api/v1/events" + (qs.toString() ? "?" + qs.toString() : "");
  const r = await fetch(url);
  if (!r.ok) throw new Error(`Events failed: ${r.status}`);
  return r.json();
}

export async function fetchSessions(): Promise<{ sessions: SessionSummary[] }> {
  const r = await fetch("/api/v1/sessions");
  if (!r.ok) throw new Error(`Sessions failed: ${r.status}`);
  return r.json();
}

export async function fetchSessionDetail(sessionId: string): Promise<SessionDetail> {
  const r = await fetch(`/api/v1/sessions/${encodeURIComponent(sessionId)}`);
  if (!r.ok) throw new Error(`Session detail failed: ${r.status}`);
  return r.json();
}

export async function verifyChain(sessionId?: string): Promise<VerifyResponse> {
  const r = await fetch("/api/v1/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sessionId ? { session_id: sessionId } : {}),
  });
  if (!r.ok) throw new Error(`Verify failed: ${r.status}`);
  return r.json();
}

export async function fetchHealth(): Promise<HealthResponse> {
  const r = await fetch("/health");
  if (!r.ok) throw new Error(`Health failed: ${r.status}`);
  return r.json();
}

// ── SSE stream ────────────────────────────────────────────────────

export function createEventStream(
  onEvent: (event: EventRecord) => void,
  onStatusChange?: (status: "connected" | "reconnecting" | "disconnected") => void,
): EventSource {
  const es = new EventSource("/api/v1/events/stream");

  es.addEventListener("connected", () => {
    if (onStatusChange) onStatusChange("connected");
  });

  es.addEventListener("new_event", (e: MessageEvent) => {
    try {
      const event: EventRecord = JSON.parse(e.data);
      onEvent(event);
    } catch {
      // Ignore malformed events
    }
  });

  es.addEventListener("ping", () => {
    // Keepalive — no action needed
  });

  es.onerror = () => {
    if (onStatusChange) onStatusChange("reconnecting");
  };

  return es;
}
