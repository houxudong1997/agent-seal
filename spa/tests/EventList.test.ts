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
    expect(screen.queryByText("Loading events…")).not.toBeInTheDocument();
  });
}

// ─── Tests ─────────────────────────────────────────────────────────

describe("EventList", () => {
  it("shows loading state when no events and historical fetch is pending", () => {
    mockFetch.mockReturnValue(new Promise(() => {})); // never resolves
    render(EventList, { props: { liveEvents: [] } });

    expect(screen.getByText("Loading events…")).toBeInTheDocument();
  });

  it("shows empty state when no live events and fetch returns empty", async () => {
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [] } });

    await waitFor(() => {
      expect(
        screen.getByText("No events yet. Waiting for activity…"),
      ).toBeInTheDocument();
    });
  });

  it("renders events from the liveEvents prop", async () => {
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: liveEventsFixture } });

    // Wait for historical fetch to settle, then check live events rendered
    await waitForLoadComplete();

    // Both live events should be in the table
    expect(screen.getByText("evt-live-1")).toBeInTheDocument();
    expect(screen.getByText("evt-live-2")).toBeInTheDocument();

    // Live events are reversed: [...liveEvents].reverse() puts evt-live-2 first
    // because it was last in the array. So table rows: evt-live-2 then evt-live-1.
    const rows = screen.getAllByRole("row");
    // row[0] is header, row[1] = evt-live-2, row[2] = evt-live-1
    expect(rows[1].textContent).toContain("evt-live-2");
    expect(rows[2].textContent).toContain("evt-live-1");
  });

  it("toggles search/filters bar when clicking the button", async () => {
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [] } });

    await waitForLoadComplete();

    // Search bar hidden by default
    expect(
      screen.queryByPlaceholderText("Search by session ID…"),
    ).not.toBeInTheDocument();

    // Click "Filters" to show
    fireEvent.click(screen.getByText("Filters"));
    expect(
      screen.getByPlaceholderText("Search by session ID…"),
    ).toBeInTheDocument();

    // Click "Hide Filters" to hide again
    fireEvent.click(screen.getByText("Hide Filters"));
    expect(
      screen.queryByPlaceholderText("Search by session ID…"),
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
    const input = screen.getByPlaceholderText("Search by session ID…");
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
    // Provide events so there are event_types to populate the <select>
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

    // Show search bar
    fireEvent.click(screen.getByText("Filters"));

    // Select a type from the dropdown
    const select = screen.getByRole("option", { name: "decision" });
    // Set parent <select> value
    const selectEl = select.closest("select")!;
    fireEvent.change(selectEl, { target: { value: "decision" } });

    // Click Search
    fireEvent.click(screen.getByText("Search"));

    // Wait for the search-triggered fetch to include event_type
    await waitFor(() => {
      const lastUrl = callUrls[callUrls.length - 1];
      expect(lastUrl).toContain("event_type=decision");
    });
  });

  it("removes duplicates when live event_id overlaps with historical", async () => {
    // Live events are reversed: last element in the array becomes first.
    // When a live event has the same event_id as a historical one, the historical
    // copy is skipped (dedup by event_id).
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

    // evt-common appears in liveEvents and historical — dedup means only 1 row
    expect(screen.getAllByText("evt-common").length).toBe(1);
    // evt-unique-live appears from liveEvents
    expect(screen.getByText("evt-unique-live")).toBeInTheDocument();
    // evt-common from historical was deduped, so total = 2
    expect(screen.getByText("2 events")).toBeInTheDocument();
  });

  it("shows event detail panel when clicking a row", async () => {
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: liveEventsFixture } });
    await waitForLoadComplete();

    // Click the first event row
    fireEvent.click(screen.getByText("evt-live-1"));

    // Detail heading is unique ("Event Detail — evt-live-1")
    expect(
      screen.getByText("Event Detail — evt-live-1"),
    ).toBeInTheDocument();
    expect(screen.getByText("✕ Close")).toBeInTheDocument();
  });

  it("detail panel shows all standard fields", async () => {
    const event = makeEvent({
      event_id: "evt-detail-1",
      session_id: "sess-detail",
      sequence: 42,
      event_type: "guardrail",
      agent_id: "agent-delta",
      prompt_version: "v2.0",
      timestamp: 1_700_123_456,
      hash: "0xcafe",
      prev_hash: "0xbabe",
    });
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [event] } });
    await waitForLoadComplete();

    // Click row
    fireEvent.click(screen.getByText("evt-detail-1"));

    // Detail heading
    expect(
      screen.getByText((content) => content.includes("Event Detail")),
    ).toBeInTheDocument();

    // Fields that appear only in the detail panel (not in the table row)
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("v2.0")).toBeInTheDocument();
    expect(screen.getByText("0xcafe")).toBeInTheDocument();
    expect(screen.getByText("0xbabe")).toBeInTheDocument();

    // Fields that appear in BOTH the table row and the detail panel
    expect(screen.getAllByText("sess-detail").length).toBe(2);
    expect(screen.getAllByText("guardrail").length).toBe(2);
    expect(screen.getAllByText("agent-delta").length).toBe(2);
  });

  it("shows '(genesis)' for prev_hash when it is empty", async () => {
    const event = makeEvent({
      event_id: "evt-genesis",
      prev_hash: "",
    });
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [event] } });
    await waitForLoadComplete();

    fireEvent.click(screen.getByText("evt-genesis"));
    expect(screen.getByText("(genesis)")).toBeInTheDocument();
  });

  it("closes the detail panel when clicking the Close button", async () => {
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: liveEventsFixture } });
    await waitForLoadComplete();

    // Open detail
    fireEvent.click(screen.getByText("evt-live-1"));
    expect(
      screen.getByText("Event Detail — evt-live-1"),
    ).toBeInTheDocument();

    // Close
    fireEvent.click(screen.getByText("✕ Close"));

    // Detail should be gone
    expect(
      screen.queryByText("Event Detail — evt-live-1"),
    ).not.toBeInTheDocument();
  });

  it("shows input_snapshot section when present", async () => {
    const event = makeEvent({
      event_id: "evt-snap",
      input_snapshot: '{"prompt": "Hello"}',
    });
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [event] } });
    await waitForLoadComplete();

    fireEvent.click(screen.getByText("evt-snap"));

    // Input section heading
    expect(screen.getByText("Input")).toBeInTheDocument();
    // The snapshot content rendered in <pre>
    expect(
      screen.getByText('{"prompt": "Hello"}'),
    ).toBeInTheDocument();
  });

  it("shows output_snapshot section when present", async () => {
    const event = makeEvent({
      event_id: "evt-out",
      output_snapshot: '{"result": "ok"}',
    });
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [event] } });
    await waitForLoadComplete();

    fireEvent.click(screen.getByText("evt-out"));

    expect(screen.getByText("Output")).toBeInTheDocument();
    expect(
      screen.getByText('{"result": "ok"}'),
    ).toBeInTheDocument();
  });

  it("shows metadata section when metadata is non-empty", async () => {
    const event = makeEvent({
      event_id: "evt-meta",
      metadata: { source: "test", priority: 3 },
    });
    mockFetch.mockResolvedValue(mockEventsResponse({ events: [] }));
    render(EventList, { props: { liveEvents: [event] } });
    await waitForLoadComplete();

    fireEvent.click(screen.getByText("evt-meta"));

    expect(screen.getByText("Metadata")).toBeInTheDocument();
    // JSON.stringify formatted
    expect(screen.getByText('{ "source": "test", "priority": 3 }')).toBeInTheDocument();
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

    fireEvent.click(screen.getByText("evt-no-snap"));

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

    fireEvent.click(screen.getByText("evt-empty-meta"));

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

    // Historical event should appear in the table
    expect(screen.getByText("evt-hist-1")).toBeInTheDocument();
    // Combined count
    expect(screen.getByText("1 events")).toBeInTheDocument();
  });
});
