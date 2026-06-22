import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/svelte";
import App from "../src/App.svelte";

// Mock global fetch with URL routing
let mockEventSource: any;
let originalEventSource: any;

function fakeResponse(data: unknown, ok = true) {
  return { ok, json: () => Promise.resolve(data) } as Response;
}

beforeEach(() => {
  mockEventSource = {
    close: vi.fn(),
    addEventListener: vi.fn(),
    onerror: null,
  };
  originalEventSource = globalThis.EventSource;
  globalThis.EventSource = vi.fn().mockImplementation(function () {
    return mockEventSource;
  }) as any;

  // Route fetch by URL to avoid cross-component interference
  globalThis.fetch = vi.fn().mockImplementation((url: string) => {
    if (url === "/api/v1/stats") {
      return Promise.resolve(
        fakeResponse({
          total_events: 100,
          sessions: 5,
          event_types: { decision: 40, tool_call: 60 },
          integrity: "ok",
          agents: ["agent-a", "agent-b", "agent-c"],
        })
      );
    }
    if (url === "/api/v1/sessions") {
      return Promise.resolve(
        fakeResponse({
          sessions: [
            { session_id: "sess-1", event_count: 10, last_event_type: "decision", last_timestamp: 1700000000, agent_id: "agent-a", integrity: "ok" },
          ],
        })
      );
    }
    if (url === "/api/v1/events" || url.startsWith("/api/v1/events?")) {
      return Promise.resolve(fakeResponse({ events: [], total: 0, limit: 200, offset: 0 }));
    }
    if (url === "/health") {
      return Promise.resolve(fakeResponse({ status: "ok", version: "1.0.0" }));
    }
    return Promise.resolve(fakeResponse({}));
  });
});

afterEach(() => {
  globalThis.EventSource = originalEventSource;
});

describe("App (integration)", () => {
  it("renders the dashboard title and version tag", async () => {
    render(App);
    expect(screen.getByText("Agent Audit Dashboard")).toBeInTheDocument();
    expect(screen.getByText("v1.0.0")).toBeInTheDocument();
  });

  it("shows three tab buttons: Live Events, Sessions, Compliance", async () => {
    render(App);
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Live Events" })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: "Sessions" })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: "Compliance" })).toBeInTheDocument();
    });
  });

  it("starts with Live Events tab active", async () => {
    render(App);
    const eventsTab = screen.getByRole("tab", { name: "Live Events" });
    expect(eventsTab.className).toContain("active");
    expect(eventsTab.getAttribute("aria-selected")).toBe("true");
  });

  it("switches to Sessions tab when clicked", async () => {
    render(App);
    const sessionsTab = screen.getByRole("tab", { name: "Sessions" });
    await fireEvent.click(sessionsTab);

    expect(sessionsTab.className).toContain("active");
    // Wait for fetch to resolve — SessionList will show the session or empty state
    await waitFor(() => {
      expect(screen.getByText("sess-1")).toBeInTheDocument();
    });
  });

  it("switches to Compliance tab when clicked", async () => {
    render(App);
    const complianceTab = screen.getByRole("tab", { name: "Compliance" });
    await fireEvent.click(complianceTab);

    expect(complianceTab.className).toContain("active");
    await waitFor(() => {
      expect(screen.getByText("Health Status")).toBeInTheDocument();
      expect(screen.getByText("Chain Verification")).toBeInTheDocument();
      expect(screen.getByText("Evidence Pack")).toBeInTheDocument();
    });
  });

  it("renders StatsCards labels inside the dashboard", async () => {
    render(App);
    await waitFor(() => {
      expect(screen.getByText("Total Events")).toBeInTheDocument();
      expect(screen.getByText("Chain Integrity")).toBeInTheDocument();
      expect(screen.getByText("Event Types")).toBeInTheDocument();
      expect(screen.getByText("Agents")).toBeInTheDocument();
    });
    // "Sessions" appears in both StatsCards label and tab button — confirm at least 2 instances
    const sessionsTexts = screen.getAllByText("Sessions");
    expect(sessionsTexts.length).toBeGreaterThanOrEqual(2);
  });

  it("creates an SSE EventSource on mount", () => {
    render(App);
    expect(globalThis.EventSource).toHaveBeenCalledWith("/api/v1/events/stream");
  });

  it("closes the EventSource on unmount (cleanup)", () => {
    const { unmount } = render(App);
    unmount();
    expect(mockEventSource.close).toHaveBeenCalled();
  });

  it("loads stats from the API and shows them", async () => {
    render(App);
    await waitFor(() => {
      expect(screen.getByText("100")).toBeInTheDocument();
      expect(screen.getByText("5")).toBeInTheDocument();
      expect(screen.getByText("✓ Intact")).toBeInTheDocument();
    });
  });
});
