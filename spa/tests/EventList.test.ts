import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/svelte";
import EventList from "../src/lib/EventList.svelte";
import type { EventRecord } from "../src/lib/api";

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function mockEventsResponse(
  data: { events: EventRecord[]; total?: number },
  ok = true,
) {
  return {
    ok,
    json: () =>
      Promise.resolve({
        events: data.events,
        total: data.total ?? data.events.length,
        limit: 200,
        offset: 0,
      }),
  } as Response;
}

function makeEvent(overrides: Partial<EventRecord> = {}): EventRecord {
  return {
    event_id: "evt-001",
    session_id: "sess-abc",
    sequence: 1,
    timestamp: 1_700_000_000,
    event_type: "decision",
    agent_id: "agent-alpha",
    prompt_version: "v1.0",
    input_snapshot: undefined,
    output_snapshot: undefined,
    metadata: undefined,
    prev_hash: "",
    hash: "0xdeadbeef",
    ...overrides,
  };
}

const liveEventsFixture: EventRecord[] = [
  makeEvent({
    event_id: "evt-live-1",
    session_id: "sess-live",
    sequence: 5,
    timestamp: 1_700_000_005,
    event_type: "tool_call",
    agent_id: "agent-beta",
    prompt_version: "v1.1",
    hash: "0xaaa",
    prev_hash: "0x999",
  }),
  makeEvent({
    event_id: "evt-live-2",
    session_id: "sess-live",
    sequence: 4,
    timestamp: 1_700_000_004,
    event_type: "model_request",
    agent_id: "agent-gamma",
    prompt_version: "v1.0",
    hash: "0xbbb",
    prev_hash: "0xaaa",
  }),
];

beforeEach(() => {
  mockFetch.mockReset();
});

// ─── Helpers ───────────────────────────────────────────────────────

/** Wait until the component is no longer loading (historical fetch resolved). */
async function waitForLoadComplete() {
  await waitFor(() => {
    expect(screen.queryByText("Loading events...")).not.toBeInTheDocument();
  });
}

/** Click a row by its data-event-id attribute. */
function clickRow(eventId: string) {
  const row = document.querySelector(`tr[data-event-id="${eventId}"]`);
  if (!row) throw new Error(`Row not found: ${eventId}`);
  fireEvent.click(row);
}

/** Get an expanded detail row if present. */
function getExpandedRow(eventId: string): Element | null {
  return document.querySelector(`tr[data-event-id="${eventId}"]`);
}

// ─── Tests ─────────────────────────────────────────────────────────

describe("EventList", () => {
  it("shows loading state when no events and historical fetch is pending", () => {
    mockFetch.mockReturnValue(new Promise(() => {})); // never resolves
    render(EventList, { props: { liveEvents: [] } });

    expect(screen.getByText("Loading events...")).toBeInTheDocument();
  });

  it("shows empty state when no live events and fetch returns empty", async () => {
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [] } });

    await waitFor(() => {
      expect(
        screen.getByText("No events yet. Waiting for activity..."),
      ).toBeInTheDocument();
    });
  });

  it("renders events from the liveEvents prop", async () => {
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: liveEventsFixture } });

    await waitForLoadComplete();

    // Both live events should have rows in the table
    expect(getExpandedRow("evt-live-1")).not.toBeNull();
    expect(getExpandedRow("evt-live-2")).not.toBeNull();

    // Live events are reversed in the table
    const rows = screen.getAllByRole("row");
    // row[0] is header, row[1] = evt-live-2, row[2] = evt-live-1
    const row1Id = rows[1].getAttribute("data-event-id");
    const row2Id = rows[2].getAttribute("data-event-id");
    expect(row1Id).toBe("evt-live-2");
    expect(row2Id).toBe("evt-live-1");
  });

  it("toggles search/filters bar when clicking the button", async () => {
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [] } });

    await waitForLoadComplete();

    // Search bar hidden by default
    expect(
      screen.queryByPlaceholderText("Search by session ID..."),
    ).not.toBeInTheDocument();

    // Click "Filters" to show
    fireEvent.click(screen.getByText("Filters"));
    expect(
      screen.getByPlaceholderText("Search by session ID..."),
    ).toBeInTheDocument();

    // Click "Hide" to hide again
    fireEvent.click(screen.getByText("Hide"));
    expect(
      screen.queryByPlaceholderText("Search by session ID..."),
    ).not.toBeInTheDocument();
  });

  it("searches by session_id when typing and clicking Search", async () => {
    const callUrls: string[] = [];
    mockFetch.mockImplementation((url: string) => {
      callUrls.push(url);
      return Promise.resolve(mockEventsResponse({ events: [] }));
    });
    render(EventList, { props: { liveEvents: [] } });
    await waitForLoadComplete();

    // Show search bar
    fireEvent.click(screen.getByText("Filters"));

    // Type a session ID
    const input = screen.getByPlaceholderText("Search by session ID...");
    await fireEvent.input(input, { target: { value: "sess-target" } });

    // Click Search
    fireEvent.click(screen.getByText("Search"));

    // Wait for the search-triggered fetch
    await waitFor(() => {
      const lastUrl = callUrls[callUrls.length - 1];
      expect(lastUrl).toContain("session_id=sess-target");
    });
  });

  it("filters by event_type when selecting a type and clicking Search", async () => {
    const historical: EventRecord[] = [
      makeEvent({ event_id: "evt-h-1", event_type: "decision" }),
      makeEvent({ event_id: "evt-h-2", event_type: "tool_call" }),
    ];
    const callUrls: string[] = [];
    mockFetch.mockImplementation((url: string) => {
      callUrls.push(url);
      return Promise.resolve(mockEventsResponse({ events: historical }));
    });
    render(EventList, { props: { liveEvents: [] } });
    await waitForLoadComplete();

    fireEvent.click(screen.getByText("Filters"));

    const select = screen.getByRole("option", { name: "decision" });
    const selectEl = select.closest("select")!;
    fireEvent.change(selectEl, { target: { value: "decision" } });

    fireEvent.click(screen.getByText("Search"));

    await waitFor(() => {
      const lastUrl = callUrls[callUrls.length - 1];
      expect(lastUrl).toContain("event_type=decision");
    });
  });

  it("removes duplicates when live event_id overlaps with historical", async () => {
    const liveEvents = [
      makeEvent({ event_id: "evt-common", timestamp: 1_700_000_001 }),
      makeEvent({ event_id: "evt-unique-live", timestamp: 1_700_000_002 }),
    ];

    mockFetch.mockResolvedValue(
      mockEventsResponse({
        events: [
          makeEvent({ event_id: "evt-common", timestamp: 1_600_000_000 }),
        ],
      }),
    );
    render(EventList, { props: { liveEvents } });
    await waitForLoadComplete();

    // Only one row per unique event_id
    const commonRows = document.querySelectorAll('tr[data-event-id="evt-common"]');
    expect(commonRows.length).toBe(1);

    expect(getExpandedRow("evt-unique-live")).not.toBeNull();
    expect(screen.getByText("2 events")).toBeInTheDocument();
  });

  it("shows inline expanded detail when clicking a row", async () => {
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: liveEventsFixture } });
    await waitForLoadComplete();

    // Click the first event row to expand inline
    clickRow("evt-live-1");

    // Expanded content should show Full Event JSON toggle
    expect(screen.getByText("Full Event JSON")).toBeInTheDocument();
    expect(screen.getByText("seq #5")).toBeInTheDocument();
  });

  it("expanded row shows sequence chips and hashes", async () => {
    const event = makeEvent({
      event_id: "evt-detail-test",
      session_id: "sess-detail",
      sequence: 42,
      event_type: "guardrail",
      agent_id: "agent-delta",
      prompt_version: "v2.0",
      timestamp: 1_700_123_456,
      hash: "0xcafebabe12345678",
      prev_hash: "0xbabebabe87654321",
    });
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [event] } });
    await waitForLoadComplete();

    clickRow("evt-detail-test");

    expect(screen.getByText("seq #42")).toBeInTheDocument();
    expect(screen.getByText("Full Event JSON")).toBeInTheDocument();
    // Hash footer shows truncated hashes with ellipsis
    expect(screen.getByText(/hash: 0xcafebabe123456/)).toBeInTheDocument();
    expect(screen.getByText(/← 0xbabebabe876543/)).toBeInTheDocument();
  });

  it("shows '(genesis)' for prev_hash when it is empty", async () => {
    const event = makeEvent({
      event_id: "evt-genesis",
      prev_hash: "",
    });
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [event] } });
    await waitForLoadComplete();

    clickRow("evt-genesis");
    // prev_hash shows "← (genesis)" in the hash footer
    expect(screen.getByText(/\(genesis\)/)).toBeInTheDocument();
  });

  it("closes expanded row when clicking again", async () => {
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: liveEventsFixture } });
    await waitForLoadComplete();

    clickRow("evt-live-1");
    expect(screen.getByText("Full Event JSON")).toBeInTheDocument();

    // Click again to collapse
    clickRow("evt-live-1");

    await waitFor(() => {
      expect(screen.queryByText("Full Event JSON")).not.toBeInTheDocument();
    });
  });

  it("shows input_snapshot section when present", async () => {
    const event = makeEvent({
      event_id: "evt-snap",
      input_snapshot: '{"prompt": "Hello"}',
    });
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [event] } });
    await waitForLoadComplete();

    clickRow("evt-snap");

    expect(screen.getByText("Input")).toBeInTheDocument();
    // Content appears in both summary column and section preview
    expect(screen.getAllByText('{"prompt": "Hello"}').length).toBeGreaterThanOrEqual(2);
  });

  it("shows output_snapshot section when present", async () => {
    const event = makeEvent({
      event_id: "evt-out",
      output_snapshot: '{"result": "ok"}',
    });
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [event] } });
    await waitForLoadComplete();

    clickRow("evt-out");

    expect(screen.getByText("Output")).toBeInTheDocument();
    // Content appears in both summary column and section preview
    expect(screen.getAllByText('{"result": "ok"}').length).toBeGreaterThanOrEqual(2);
  });

  it("shows metadata section when metadata is non-empty", async () => {
    const event = makeEvent({
      event_id: "evt-meta",
      metadata: { source: "test", priority: 3 },
    });
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [event] } });
    await waitForLoadComplete();

    clickRow("evt-meta");

    expect(screen.getByText("Metadata")).toBeInTheDocument();
    expect(screen.getByText("source, priority")).toBeInTheDocument();
  });

  it("does not show input/output/metadata sections when absent", async () => {
    const event = makeEvent({
      event_id: "evt-no-snap",
      input_snapshot: undefined,
      output_snapshot: undefined,
      metadata: undefined,
    });
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [event] } });
    await waitForLoadComplete();

    clickRow("evt-no-snap");

    expect(screen.getByText("Full Event JSON")).toBeInTheDocument();
    expect(screen.queryByText("Input")).not.toBeInTheDocument();
    expect(screen.queryByText("Output")).not.toBeInTheDocument();
    expect(screen.queryByText("Metadata")).not.toBeInTheDocument();
  });

  it("does not show metadata section when metadata is empty object", async () => {
    const event = makeEvent({
      event_id: "evt-empty-meta",
      metadata: {},
    });
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [event] } });
    await waitForLoadComplete();

    clickRow("evt-empty-meta");

    expect(screen.queryByText("Metadata")).not.toBeInTheDocument();
  });

  it("displays event count in the header", async () => {
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: liveEventsFixture } });
    await waitForLoadComplete();

    expect(screen.getByText("2 events")).toBeInTheDocument();
  });

  it("includes historical events after fetch resolves", async () => {
    const historical: EventRecord[] = [
      makeEvent({
        event_id: "evt-hist-1",
        session_id: "sess-hist",
        timestamp: 1_600_000_000,
        event_type: "model_request",
        agent_id: "agent-hist",
      }),
    ];
    mockFetch.mockResolvedValue(mockEventsResponse({ events: historical }));
    render(EventList, { props: { liveEvents: [] } });
    await waitForLoadComplete();

    // Historical event should have a row
    expect(getExpandedRow("evt-hist-1")).not.toBeNull();
    expect(screen.getByText("1 events")).toBeInTheDocument();
  });

  it("shows summary column with event content in table", async () => {
    const event = makeEvent({
      event_id: "evt-sum",
      event_type: "llm_request",
      input_snapshot: "What is the capital of France?",
      metadata: { model: "deepseek-v4", ms: 1234, status: 200 },
    });
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [event] } });
    await waitForLoadComplete();

    // Summary column should show prompt preview
    expect(screen.getByText(/What is the capital/)).toBeInTheDocument();
  });

  it("shows LLM error in summary column", async () => {
    const event = makeEvent({
      event_id: "evt-llm-err",
      event_type: "llm_error",
      metadata: { error: "Connection timed out" },
    });
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [event] } });
    await waitForLoadComplete();

    expect(screen.getByText(/Connection timed out/)).toBeInTheDocument();
  });

  it("shows expanded error banner for error events", async () => {
    const event = makeEvent({
      event_id: "evt-err-banner",
      event_type: "llm_error",
      metadata: { error: "Connection timed out after 30s" },
    });
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [event] } });
    await waitForLoadComplete();

    clickRow("evt-err-banner");

    expect(
      screen.getByText("Connection timed out after 30s"),
    ).toBeInTheDocument();
  });
});
