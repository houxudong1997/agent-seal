import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  fetchStats,
  fetchEvents,
  fetchSessions,
  fetchSessionDetail,
  verifyChain,
  fetchHealth,
  createEventStream,
} from "../src/lib/api";
import type { Mock } from "vitest";

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

// Helper to create a mock Response
function mockResponse(data: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  } as Response;
}

describe("api.ts", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  // ── fetchStats ───────────────────────────────────────────────
  describe("fetchStats", () => {
    it("fetches stats from /api/v1/stats", async () => {
      const statsData = {
        total_events: 42,
        sessions: 5,
        event_types: { decision: 20, tool_call: 22 },
        integrity: "ok" as const,
        agents: ["agent-a", "agent-b"],
      };
      mockFetch.mockResolvedValue(mockResponse(statsData));

      const result = await fetchStats();
      expect(mockFetch).toHaveBeenCalledWith("/api/v1/stats");
      expect(result).toEqual(statsData);
    });

    it("throws on non-ok response", async () => {
      mockFetch.mockResolvedValue(mockResponse(null, false, 500));
      await expect(fetchStats()).rejects.toThrow("Stats failed: 500");
    });
  });

  // ── fetchEvents ──────────────────────────────────────────────
  describe("fetchEvents", () => {
    const eventsResponse = {
      events: [{ event_id: "evt-1" }],
      total: 1,
      limit: 200,
      offset: 0,
    };

    it("fetches events with no params", async () => {
      mockFetch.mockResolvedValue(mockResponse(eventsResponse));
      const result = await fetchEvents();
      expect(mockFetch).toHaveBeenCalledWith("/api/v1/events");
      expect(result).toEqual(eventsResponse);
    });

    it("applies session_id filter", async () => {
      mockFetch.mockResolvedValue(mockResponse(eventsResponse));
      await fetchEvents({ session_id: "sess-1" });
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/v1/events?session_id=sess-1"
      );
    });

    it("applies event_type filter", async () => {
      mockFetch.mockResolvedValue(mockResponse(eventsResponse));
      await fetchEvents({ event_type: "decision" });
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/v1/events?event_type=decision"
      );
    });

    it("applies multiple filters", async () => {
      mockFetch.mockResolvedValue(mockResponse(eventsResponse));
      await fetchEvents({ session_id: "sess-1", event_type: "decision", limit: 50, offset: 10 });
      const url = (mockFetch.mock.calls[0][0] as string);
      expect(url).toContain("session_id=sess-1");
      expect(url).toContain("event_type=decision");
      expect(url).toContain("limit=50");
      expect(url).toContain("offset=10");
    });

    it("throws on non-ok response", async () => {
      mockFetch.mockResolvedValue(mockResponse(null, false, 404));
      await expect(fetchEvents()).rejects.toThrow("Events failed: 404");
    });
  });

  // ── fetchSessions ────────────────────────────────────────────
  describe("fetchSessions", () => {
    it("fetches sessions from /api/v1/sessions", async () => {
      const sessionsData = {
        sessions: [{ session_id: "sess-1", event_count: 10 }],
      };
      mockFetch.mockResolvedValue(mockResponse(sessionsData));
      const result = await fetchSessions();
      expect(mockFetch).toHaveBeenCalledWith("/api/v1/sessions");
      expect(result).toEqual(sessionsData);
    });

    it("throws on non-ok response", async () => {
      mockFetch.mockResolvedValue(mockResponse(null, false, 503));
      await expect(fetchSessions()).rejects.toThrow("Sessions failed: 503");
    });
  });

  // ── fetchSessionDetail ───────────────────────────────────────
  describe("fetchSessionDetail", () => {
    it("fetches session detail with encoded ID", async () => {
      const detail = { session_id: "sess-1", events: [] };
      mockFetch.mockResolvedValue(mockResponse(detail));
      const result = await fetchSessionDetail("sess-1");
      expect(mockFetch).toHaveBeenCalledWith("/api/v1/sessions/sess-1");
      expect(result).toEqual(detail);
    });

    it("URL-encodes session ID", async () => {
      mockFetch.mockResolvedValue(mockResponse({}));
      await fetchSessionDetail("sess/1");
      expect(mockFetch).toHaveBeenCalledWith("/api/v1/sessions/sess%2F1");
    });

    it("throws on non-ok response", async () => {
      mockFetch.mockResolvedValue(mockResponse(null, false, 404));
      await expect(fetchSessionDetail("bogus")).rejects.toThrow("Session detail failed: 404");
    });
  });

  // ── verifyChain ──────────────────────────────────────────────
  describe("verifyChain", () => {
    it("verifies all sessions", async () => {
      const result = { integrity: "ok" as const };
      mockFetch.mockResolvedValue(mockResponse(result));
      const res = await verifyChain();
      expect(mockFetch).toHaveBeenCalledWith("/api/v1/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      expect(res).toEqual(result);
    });

    it("verifies a single session", async () => {
      const result = { integrity: "ok" as const, session_id: "sess-1" };
      mockFetch.mockResolvedValue(mockResponse(result));
      const res = await verifyChain("sess-1");
      expect(mockFetch).toHaveBeenCalledWith("/api/v1/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: "sess-1" }),
      });
      expect(res).toEqual(result);
    });

    it("throws on non-ok response", async () => {
      mockFetch.mockResolvedValue(mockResponse(null, false, 502));
      await expect(verifyChain()).rejects.toThrow("Verify failed: 502");
    });
  });

  // ── fetchHealth ──────────────────────────────────────────────
  describe("fetchHealth", () => {
    it("fetches health from /health", async () => {
      const health = { status: "ok", version: "1.0.0" };
      mockFetch.mockResolvedValue(mockResponse(health));
      const result = await fetchHealth();
      expect(mockFetch).toHaveBeenCalledWith("/health");
      expect(result).toEqual(health);
    });

    it("throws on non-ok response", async () => {
      mockFetch.mockResolvedValue(mockResponse(null, false, 500));
      await expect(fetchHealth()).rejects.toThrow("Health failed: 500");
    });
  });

  // ── createEventStream ────────────────────────────────────────
  describe("createEventStream", () => {
    let mockEventSource: any;
    let originalEventSource: any;

    beforeEach(() => {
      mockEventSource = {
        close: vi.fn(),
        addEventListener: vi.fn(),
        onerror: null,
      };
      originalEventSource = globalThis.EventSource;
      // Must use a constructor function for `new EventSource(...)` to work
      globalThis.EventSource = vi.fn().mockImplementation(function () {
        return mockEventSource;
      }) as any;
    });

    afterEach(() => {
      globalThis.EventSource = originalEventSource;
    });

    it("creates EventSource to /api/v1/events/stream", () => {
      createEventStream(vi.fn());
      expect(globalThis.EventSource).toHaveBeenCalledWith("/api/v1/events/stream");
    });

    it("calls onEvent when new_event is received", () => {
      const onEvent = vi.fn();
      createEventStream(onEvent);
      const addEventListenerCalls = mockEventSource.addEventListener.mock.calls;
      const newEventCall = addEventListenerCalls.find(
        (c: any[]) => c[0] === "new_event"
      );
      expect(newEventCall).toBeDefined();

      const eventData = { event_id: "evt-1", session_id: "sess-1" };
      newEventCall[1]({ data: JSON.stringify(eventData) });
      expect(onEvent).toHaveBeenCalledWith(eventData);
    });

    it("handles malformed JSON in new_event gracefully", () => {
      const onEvent = vi.fn();
      createEventStream(onEvent);
      const addEventListenerCalls = mockEventSource.addEventListener.mock.calls;
      const newEventCall = addEventListenerCalls.find(
        (c: any[]) => c[0] === "new_event"
      );

      newEventCall[1]({ data: "not-json" });
      expect(onEvent).not.toHaveBeenCalled();
    });

    it("calls onStatusChange when connected event fires", () => {
      const onStatusChange = vi.fn();
      createEventStream(vi.fn(), onStatusChange);
      const addEventListenerCalls = mockEventSource.addEventListener.mock.calls;
      const connectedCall = addEventListenerCalls.find(
        (c: any[]) => c[0] === "connected"
      );
      connectedCall[1]();
      expect(onStatusChange).toHaveBeenCalledWith("connected");
    });

    it("calls onStatusChange with reconnecting on error", () => {
      const onStatusChange = vi.fn();
      createEventStream(vi.fn(), onStatusChange);
      mockEventSource.onerror();
      expect(onStatusChange).toHaveBeenCalledWith("reconnecting");
    });

    it("registers ping listener", () => {
      createEventStream(vi.fn());
      const addEventListenerCalls = mockEventSource.addEventListener.mock.calls;
      const pingCall = addEventListenerCalls.find(
        (c: any[]) => c[0] === "ping"
      );
      expect(pingCall).toBeDefined();
    });

    it("returns the EventSource for cleanup", () => {
      const es = createEventStream(vi.fn());
      expect(es).toBe(mockEventSource);
      expect(es.close).toBeDefined();
    });
  });
});
