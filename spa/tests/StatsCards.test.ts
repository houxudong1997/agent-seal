import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import StatsCards from "../src/lib/StatsCards.svelte";

// Mock fetch for stats
const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function mockResponse(data: unknown, ok = true) {
  return { ok, json: () => Promise.resolve(data) } as Response;
}

describe("StatsCards", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("shows loading state with dashes initially", () => {
    mockFetch.mockResolvedValue(new Promise(() => {})); // Never resolves
    const { container } = render(StatsCards);
    const dashes = container.querySelectorAll(".value");
    expect(dashes.length).toBeGreaterThan(0);
    // All stats should show "--" while loading
    const eventValue = container.querySelector(".value.events");
    expect(eventValue?.textContent).toBe("--");
  });

  it("renders stats data from API", async () => {
    mockFetch.mockResolvedValue(
      mockResponse({
        total_events: 100,
        sessions: 5,
        event_types: { decision: 40, tool_call: 60 },
        integrity: "ok",
        agents: ["agent-a", "agent-b", "agent-c"],
      })
    );

    render(StatsCards);

    await waitFor(() => {
      expect(screen.getByText("100")).toBeInTheDocument();
    });

    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("✓ Intact")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument(); // Object.keys(event_types).length
    expect(screen.getByText("3")).toBeInTheDocument(); // agents.length
  });

  it("shows broken integrity when chain is broken", async () => {
    mockFetch.mockResolvedValue(
      mockResponse({
        total_events: 50,
        sessions: 2,
        event_types: { decision: 30 },
        integrity: "broken",
        agents: ["agent-a"],
      })
    );

    render(StatsCards);

    await waitFor(() => {
      expect(screen.getByText("✗ Broken")).toBeInTheDocument();
    });
  });

  it("shows unknown integrity when integrity is unknown", async () => {
    mockFetch.mockResolvedValue(
      mockResponse({
        total_events: 0,
        sessions: 0,
        event_types: {},
        integrity: "unknown",
        agents: [],
      })
    );

    render(StatsCards);

    await waitFor(() => {
      expect(screen.getByText("? Unknown")).toBeInTheDocument();
    });
  });

  it("shows error toast when fetch fails", async () => {
    mockFetch.mockRejectedValue(new Error("Network error"));

    render(StatsCards);

    await waitFor(() => {
      expect(screen.getByText(/Failed to load stats/i)).toBeInTheDocument();
    });
  });
});
