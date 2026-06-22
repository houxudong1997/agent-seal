import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import SessionList from "../src/lib/SessionList.svelte";

// Mock fetch globally — the api module uses global fetch internally
const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function mockResponse(data: unknown, ok = true) {
  return { ok, json: () => Promise.resolve(data) } as Response;
}

const sampleSessions = {
  sessions: [
    {
      session_id: "ses-001",
      event_count: 10,
      last_event_type: "decision",
      last_timestamp: 1718000000,
      agent_id: "agent-alpha",
      integrity: "ok",
    },
    {
      session_id: "ses-002",
      event_count: 5,
      last_event_type: "tool_call",
      last_timestamp: 1718001000,
      agent_id: "agent-beta",
      integrity: "broken",
    },
  ],
};

const sampleDetail = {
  session_id: "ses-001",
  event_count: 10,
  integrity: "ok",
  events: [
    {
      event_id: "evt-001",
      session_id: "ses-001",
      sequence: 1,
      timestamp: 1718000000,
      event_type: "decision",
      agent_id: "agent-alpha",
      prompt_version: "v1",
      prev_hash: "0x0",
      hash: "0xabc123def456789",
    },
    {
      event_id: "evt-002",
      session_id: "ses-001",
      sequence: 2,
      timestamp: 1718000100,
      event_type: "tool_call",
      agent_id: "agent-alpha",
      prompt_version: "v1",
      prev_hash: "0xabc123def456789",
      hash: "0xdef789abc012345",
    },
  ],
};

describe("SessionList", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("shows 'Loading…' on mount before fetch resolves", () => {
    // Never-resolving promise keeps loading=true
    mockFetch.mockResolvedValue(new Promise(() => {}));
    render(SessionList);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("shows empty state when sessions list is empty", async () => {
    mockFetch.mockResolvedValue(mockResponse({ sessions: [] }));
    render(SessionList);

    await waitFor(() => {
      expect(
        screen.getByText("No sessions recorded yet"),
      ).toBeInTheDocument();
    });
  });

  it("renders session list with session_id, event_count, last_event_type, agent_id", async () => {
    mockFetch.mockResolvedValue(mockResponse(sampleSessions));
    render(SessionList);

    await waitFor(() => {
      expect(screen.getByText("ses-001")).toBeInTheDocument();
    });

    // Both sessions rendered
    expect(screen.getByText("ses-002")).toBeInTheDocument();

    // Event counts
    expect(screen.getByText(/10 events/i)).toBeInTheDocument();
    expect(screen.getByText(/5 events/i)).toBeInTheDocument();

    // Last event types
    expect(screen.getByText(/decision/i)).toBeInTheDocument();
    expect(screen.getByText(/tool_call/i)).toBeInTheDocument();

    // Agent IDs
    expect(screen.getByText(/agent-alpha/i)).toBeInTheDocument();
    expect(screen.getByText(/agent-beta/i)).toBeInTheDocument();
  });

  it("shows 'Intact' badge with badge-ok class for integrity='ok'", async () => {
    mockFetch.mockResolvedValue(mockResponse(sampleSessions));
    const { container } = render(SessionList);

    await waitFor(() => {
      expect(screen.getByText("Intact")).toBeInTheDocument();
    });

    const intactBadge = screen.getByText("Intact");
    expect(intactBadge.className).toContain("badge-ok");
    expect(intactBadge.className).not.toContain("badge-broken");
  });

  it("shows 'Broken' badge with badge-broken class for integrity!='ok'", async () => {
    mockFetch.mockResolvedValue(mockResponse(sampleSessions));
    render(SessionList);

    await waitFor(() => {
      expect(screen.getByText("Broken")).toBeInTheDocument();
    });

    const brokenBadge = screen.getByText("Broken");
    expect(brokenBadge.className).toContain("badge-broken");
  });

  it("renders timestamp text for each session", async () => {
    mockFetch.mockResolvedValue(mockResponse(sampleSessions));
    render(SessionList);

    // formatTime(1718000000) = new Date(1718000000000).toLocaleString()
    const expectedTime1 = new Date(1718000000 * 1000).toLocaleString();
    const expectedTime2 = new Date(1718001000 * 1000).toLocaleString();

    await waitFor(() => {
      expect(screen.getByText(expectedTime1)).toBeInTheDocument();
    });

    expect(screen.getByText(expectedTime2)).toBeInTheDocument();
  });

  it("clicking a session calls fetchSessionDetail and shows detail card", async () => {
    // First call: fetchSessions, second call: fetchSessionDetail
    mockFetch
      .mockResolvedValueOnce(mockResponse(sampleSessions))
      .mockResolvedValueOnce(mockResponse(sampleDetail));

    render(SessionList);

    await waitFor(() => {
      expect(screen.getByText("ses-001")).toBeInTheDocument();
    });

    // Click the first session card (event bubbles from text to parent)
    screen.getByText("ses-001").click();

    // Detail card should appear with session info
    await waitFor(() => {
      expect(screen.getByText(/Session: ses-001/)).toBeInTheDocument();
    });

    expect(screen.getByText(/10 events/)).toBeInTheDocument();
    expect(screen.getByText("Chain: Intact")).toBeInTheDocument();
  });

  it("detail card shows events table with Seq, Time, Type, Agent, Event ID, Hash columns", async () => {
    mockFetch
      .mockResolvedValueOnce(mockResponse(sampleSessions))
      .mockResolvedValueOnce(mockResponse(sampleDetail));

    render(SessionList);

    await waitFor(() => {
      expect(screen.getByText("ses-001")).toBeInTheDocument();
    });

    screen.getByText("ses-001").click();

    // Wait for events to render
    await waitFor(() => {
      expect(screen.getByText("evt-001")).toBeInTheDocument();
    });

    // Table headers
    expect(screen.getByText("Seq")).toBeInTheDocument();
    expect(screen.getByText("Time")).toBeInTheDocument();
    expect(screen.getByText("Type")).toBeInTheDocument();
    expect(screen.getByText("Agent")).toBeInTheDocument();
    expect(screen.getByText("Event ID")).toBeInTheDocument();
    expect(screen.getByText("Hash")).toBeInTheDocument();

    // Event rows
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("evt-002")).toBeInTheDocument();

    // Hash is truncated to first 12 characters
    expect(screen.getByText("0xabc123def4")).toBeInTheDocument();
    expect(screen.getByText("0xdef789abc0")).toBeInTheDocument();

    // Event type badges
    const typeBadges = document.querySelectorAll(".badge-type");
    expect(typeBadges.length).toBe(2);
  });

  it("close button hides the detail card", async () => {
    mockFetch
      .mockResolvedValueOnce(mockResponse(sampleSessions))
      .mockResolvedValueOnce(mockResponse(sampleDetail));

    render(SessionList);

    await waitFor(() => {
      expect(screen.getByText("ses-001")).toBeInTheDocument();
    });

    // Open detail
    screen.getByText("ses-001").click();

    await waitFor(() => {
      expect(screen.getByText(/Session: ses-001/)).toBeInTheDocument();
    });

    // Click close button
    const closeBtn = screen.getByText("✕ Close");
    closeBtn.click();

    await waitFor(() => {
      expect(
        screen.queryByText(/Session: ses-001/),
      ).not.toBeInTheDocument();
    });

    // Session list should still be visible
    expect(screen.getByText("ses-001")).toBeInTheDocument();
  });

  it("Refresh button re-fetches sessions and updates list", async () => {
    mockFetch.mockResolvedValue(mockResponse(sampleSessions));
    render(SessionList);

    await waitFor(() => {
      expect(screen.getByText("ses-001")).toBeInTheDocument();
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);

    // Reset and set up new data for the refresh
    mockFetch.mockReset();
    mockFetch.mockResolvedValue(
      mockResponse({
        sessions: [sampleSessions.sessions[1]], // Only ses-002
      }),
    );

    // Click Refresh
    screen.getByText("Refresh").click();

    // Wait for loading to clear and new data to appear
    await waitFor(() => {
      expect(screen.getByText("ses-002")).toBeInTheDocument();
    });

    expect(screen.queryByText("ses-001")).not.toBeInTheDocument();
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("handles fetchSessions failure gracefully (shows empty state)", async () => {
    mockFetch.mockRejectedValue(new Error("Network error"));
    render(SessionList);

    await waitFor(() => {
      expect(
        screen.getByText("No sessions recorded yet"),
      ).toBeInTheDocument();
    });
  });

  it("handles fetchSessionDetail failure gracefully (detail card not shown)", async () => {
    // First call succeeds (session list), second call fails
    mockFetch
      .mockResolvedValueOnce(mockResponse(sampleSessions))
      .mockRejectedValueOnce(new Error("Detail fetch failed"));

    render(SessionList);

    await waitFor(() => {
      expect(screen.getByText("ses-001")).toBeInTheDocument();
    });

    // Click session — fetchSessionDetail will fail
    screen.getByText("ses-001").click();

    await waitFor(() => {
      expect(
        screen.queryByText(/Session: ses-001/),
      ).not.toBeInTheDocument();
    });
  });
});
