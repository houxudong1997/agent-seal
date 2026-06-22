import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/svelte";
import ComplianceView from "../src/lib/ComplianceView.svelte";

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function mockResponse(data: unknown, ok = true) {
  return { ok, json: () => Promise.resolve(data) } as Response;
}

// Helpers to find specific elements in the grid layout
function findCard(heading: string) {
  const headingEl = screen.getByRole("heading", { name: heading });
  return headingEl.closest(".card") as HTMLElement;
}

describe("ComplianceView", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  // ── Health Status Card ──────────────────────────────────────────────

  it("shows checking state while health is loading", () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));
    render(ComplianceView);
    expect(screen.getByText("Checking…")).toBeInTheDocument();
  });

  it("shows API status and version when health resolves", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/health") {
        return Promise.resolve(
          mockResponse({ status: "healthy", version: "2.1.0" }),
        );
      }
      if (url === "/api/v1/sessions") {
        return Promise.resolve(mockResponse({ sessions: [] }));
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(ComplianceView);

    await waitFor(() => {
      expect(screen.getByText("healthy")).toBeInTheDocument();
    });

    expect(screen.getByText("2.1.0")).toBeInTheDocument();
    expect(screen.queryByText("Checking…")).not.toBeInTheDocument();
  });

  it("shows health check failed when health fetch errors", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/health") {
        return Promise.reject(new Error("Connection refused"));
      }
      if (url === "/api/v1/sessions") {
        return Promise.resolve(mockResponse({ sessions: [] }));
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(ComplianceView);

    await waitFor(() => {
      expect(screen.getByText("Health check failed")).toBeInTheDocument();
    });
  });

  it("re-fetches health when Refresh button is clicked", async () => {
    let healthCallCount = 0;
    mockFetch.mockImplementation((url: string) => {
      if (url === "/health") {
        healthCallCount++;
        return Promise.resolve(
          mockResponse({ status: "ok", version: "1.0.0" }),
        );
      }
      if (url === "/api/v1/sessions") {
        return Promise.resolve(mockResponse({ sessions: [] }));
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(ComplianceView);

    await waitFor(() => {
      expect(screen.getByText("ok")).toBeInTheDocument();
    });

    expect(healthCallCount).toBe(1);

    fireEvent.click(screen.getByText("Refresh"));

    expect(screen.getByText("Checking…")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("ok")).toBeInTheDocument();
    });

    expect(healthCallCount).toBe(2);
  });

  // ── Sessions Loading (affects prompt versions + verify selects) ────

  it("shows sessions loading state in prompt versions card", () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));
    render(ComplianceView);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("shows no sessions message when session list is empty", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/health") {
        return Promise.resolve(mockResponse({ status: "ok", version: "1" }));
      }
      if (url === "/api/v1/sessions") {
        return Promise.resolve(mockResponse({ sessions: [] }));
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(ComplianceView);

    await waitFor(() => {
      expect(screen.getByText("No sessions available")).toBeInTheDocument();
    });
  });

  it("shows sessions in prompt versions card", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/health") {
        return Promise.resolve(mockResponse({ status: "ok", version: "1" }));
      }
      if (url === "/api/v1/sessions") {
        return Promise.resolve(
          mockResponse({
            sessions: [
              {
                session_id: "sess-001",
                event_count: 10,
                last_event_type: "decision",
                last_timestamp: 1712345678,
                agent_id: "agent-a",
                integrity: "ok",
              },
              {
                session_id: "sess-002",
                event_count: 5,
                last_event_type: "tool_call",
                last_timestamp: 1712345778,
                agent_id: "agent-b",
                integrity: "broken",
              },
            ],
          }),
        );
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(ComplianceView);

    // Scope to the Prompt Versions card to avoid matches from select options
    const promptCard = findCard("Prompt Versions");
    await waitFor(() => {
      expect(promptCard.textContent).toContain("sess-001");
    });

    expect(promptCard.textContent).toContain("sess-002");
    expect(promptCard.textContent).toContain("decision");
    expect(promptCard.textContent).toContain("tool_call");
  });

  // ── Chain Verification ─────────────────────────────────────────────

  it("renders Verify All Sessions button", () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));
    render(ComplianceView);
    expect(screen.getByText("Verify All Sessions")).toBeInTheDocument();
  });

  it("calls verifyChain on Verify All and shows ok result", async () => {
    mockFetch.mockImplementation((url: string, _options?: RequestInit) => {
      if (url === "/health") {
        return Promise.resolve(mockResponse({ status: "ok", version: "1" }));
      }
      if (url === "/api/v1/sessions") {
        return Promise.resolve(mockResponse({ sessions: [] }));
      }
      if (url === "/api/v1/verify") {
        return Promise.resolve(
          mockResponse({
            integrity: "ok",
            sessions: { "sess-001": "ok", "sess-002": "ok" },
          }),
        );
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(ComplianceView);

    await waitFor(() => {
      expect(screen.queryByText("Checking…")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Verify All Sessions"));

    expect(screen.getByText("Verifying…")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("✓ All Chains Intact")).toBeInTheDocument();
    });

    // Per-session breakdown shown
    const verifyCard = findCard("Chain Verification");
    expect(verifyCard.textContent).toContain("sess-001");
    expect(verifyCard.textContent).toContain("sess-002");
    // Both show "ok" status
    const okBadges = verifyCard.querySelectorAll(".badge-ok");
    expect(okBadges.length).toBeGreaterThanOrEqual(2);
  });

  it("shows broken chain result when verify finds issues", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/health") {
        return Promise.resolve(mockResponse({ status: "ok", version: "1" }));
      }
      if (url === "/api/v1/sessions") {
        return Promise.resolve(mockResponse({ sessions: [] }));
      }
      if (url === "/api/v1/verify") {
        return Promise.resolve(
          mockResponse({
            integrity: "broken",
            sessions: { "sess-001": "ok", "sess-002": "broken" },
          }),
        );
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(ComplianceView);

    await waitFor(() => {
      expect(screen.queryByText("Checking…")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Verify All Sessions"));

    await waitFor(() => {
      expect(screen.getByText("✗ Chain(s) Broken")).toBeInTheDocument();
    });

    const verifyCard = findCard("Chain Verification");
    expect(verifyCard.textContent).toContain("sess-001");
    expect(verifyCard.textContent).toContain("sess-002");
  });

  it("verifies a single session when selected and Verify Session is clicked", async () => {
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url === "/health") {
        return Promise.resolve(mockResponse({ status: "ok", version: "1" }));
      }
      if (url === "/api/v1/sessions") {
        return Promise.resolve(
          mockResponse({
            sessions: [
              {
                session_id: "sess-001",
                event_count: 10,
                last_event_type: "decision",
                last_timestamp: 1712345678,
                agent_id: "agent-a",
                integrity: "ok",
              },
            ],
          }),
        );
      }
      if (url === "/api/v1/verify") {
        const body = options?.body ? JSON.parse(options.body as string) : {};
        if (body.session_id === "sess-001") {
          return Promise.resolve(
            mockResponse({ integrity: "broken", session_id: "sess-001" }),
          );
        }
        return Promise.resolve(mockResponse({ integrity: "ok" }));
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(ComplianceView);

    // Wait for the selected session option to appear
    const verifyCard = findCard("Chain Verification");
    await waitFor(() => {
      expect(verifyCard.textContent).toContain("sess-001");
    });

    // Select the session — first select in the Chain Verification card
    const selects = verifyCard.querySelectorAll("select");
    fireEvent.change(selects[0], { target: { value: "sess-001" } });

    fireEvent.click(screen.getByText("Verify Session"));

    await waitFor(() => {
      expect(screen.getByText("broken")).toBeInTheDocument();
    });

    expect(verifyCard.textContent).toContain("sess-001");
  });

  it("shows verify error when verifyChain fails", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/health") {
        return Promise.resolve(mockResponse({ status: "ok", version: "1" }));
      }
      if (url === "/api/v1/sessions") {
        return Promise.resolve(mockResponse({ sessions: [] }));
      }
      if (url === "/api/v1/verify") {
        return Promise.reject(new Error("Verification service unavailable"));
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(ComplianceView);

    await waitFor(() => {
      expect(screen.queryByText("Checking…")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Verify All Sessions"));

    await waitFor(() => {
      expect(
        screen.getByText(/Error: Verification service unavailable/),
      ).toBeInTheDocument();
    });
  });

  it("disables all verify buttons while a verification is in progress", async () => {
    let resolveVerify: (v: unknown) => void;
    const verifyPromise = new Promise((resolve) => {
      resolveVerify = resolve;
    });

    // Include a session so we can select it for Verify Session
    mockFetch.mockImplementation((url: string) => {
      if (url === "/health") {
        return Promise.resolve(mockResponse({ status: "ok", version: "1" }));
      }
      if (url === "/api/v1/sessions") {
        return Promise.resolve(
          mockResponse({
            sessions: [
              {
                session_id: "sess-verify",
                event_count: 5,
                last_event_type: "decision",
                last_timestamp: 1712345678,
                agent_id: "agent-a",
                integrity: "ok",
              },
            ],
          }),
        );
      }
      if (url === "/api/v1/verify") {
        return verifyPromise;
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(ComplianceView);

    // Wait for sessions to load so Verify Session button becomes enabled
    const verifyCard = findCard("Chain Verification");
    await waitFor(() => {
      expect(verifyCard.textContent).toContain("sess-verify");
    });

    // Select the session so Verify Session button is not disabled by !selectedSessionId
    const verifySelect = verifyCard.querySelector("select")!;
    fireEvent.change(verifySelect, { target: { value: "sess-verify" } });

    fireEvent.click(screen.getByText("Verify All Sessions"));

    const verifyingBtn = screen.getByText("Verifying…");
    expect(verifyingBtn).toBeDisabled();

    const verifySessionBtn = screen.getByText("Verify Session");
    expect(verifySessionBtn).toBeDisabled();

    resolveVerify!(mockResponse({ integrity: "ok" }));

    await waitFor(() => {
      expect(screen.getByText("✓ All Chains Intact")).toBeInTheDocument();
    });

    // Both buttons should re-enable after verification completes
    expect(screen.getByText("Verify All Sessions")).not.toBeDisabled();
    expect(screen.getByText("Verify Session")).not.toBeDisabled();
  });

  // ── Evidence Pack ──────────────────────────────────────────────────

  it("disables Generate Evidence Pack button when no session selected", async () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));
    render(ComplianceView);

    const generateBtn = screen.getByText("Generate Evidence Pack");
    expect(generateBtn).toBeDisabled();
  });

  it("generates and shows evidence pack data", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/health") {
        return Promise.resolve(mockResponse({ status: "ok", version: "1" }));
      }
      if (url === "/api/v1/sessions") {
        return Promise.resolve(
          mockResponse({
            sessions: [
              {
                session_id: "sess-evidence-1",
                event_count: 3,
                last_event_type: "decision",
                last_timestamp: 1712345678,
                agent_id: "agent-a",
                integrity: "ok",
              },
            ],
          }),
        );
      }
      if (url === "/api/v1/sessions/sess-evidence-1") {
        return Promise.resolve(
          mockResponse({
            session_id: "sess-evidence-1",
            event_count: 3,
            integrity: "ok",
            events: [
              {
                event_id: "evt-1",
                session_id: "sess-evidence-1",
                sequence: 0,
                timestamp: 1712345600,
                event_type: "decision",
                agent_id: "agent-alpha",
                prompt_version: "v1.0",
                prev_hash: "",
                hash: "0xabc",
              },
              {
                event_id: "evt-2",
                session_id: "sess-evidence-1",
                sequence: 1,
                timestamp: 1712345650,
                event_type: "tool_call",
                agent_id: "agent-beta",
                prompt_version: "v1.0",
                prev_hash: "0xabc",
                hash: "0xdef",
              },
              {
                event_id: "evt-3",
                session_id: "sess-evidence-1",
                sequence: 2,
                timestamp: 1712345700,
                event_type: "decision",
                agent_id: "agent-alpha",
                prompt_version: "v2.0",
                prev_hash: "0xdef",
                hash: "0xghi",
              },
            ],
          }),
        );
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(ComplianceView);

    // Wait for sessions to load — scope to evidence card
    const evidenceCard = findCard("Evidence Pack");
    await waitFor(() => {
      expect(evidenceCard.textContent).toContain("sess-evidence-1");
    });

    // Select session in evidence pack select
    const evidenceSelect = evidenceCard.querySelector("select")!;
    fireEvent.change(evidenceSelect, { target: { value: "sess-evidence-1" } });

    fireEvent.click(screen.getByText("Generate Evidence Pack"));

    expect(screen.getByText("Generating…")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("✓ Evidence Pack Ready")).toBeInTheDocument();
    });

    // Check evidence pack fields (within evidence card to avoid duplicates)
    expect(evidenceCard.textContent).toContain("3"); // Total Events & Hash Count

    // Event types chips (scope to evidence card to avoid prompt list matches)
    const evidenceChips = within(evidenceCard);
    expect(evidenceChips.getByText("decision")).toBeInTheDocument();
    expect(evidenceChips.getByText("tool_call")).toBeInTheDocument();

    // Agents chips
    expect(evidenceChips.getByText("agent-alpha")).toBeInTheDocument();
    expect(evidenceChips.getByText("agent-beta")).toBeInTheDocument();

    // Prompt versions chips
    expect(evidenceChips.getByText("v1.0")).toBeInTheDocument();
    expect(evidenceChips.getByText("v2.0")).toBeInTheDocument();

    const firstExpected = new Date(1712345600 * 1000).toISOString();
    const lastExpected = new Date(1712345700 * 1000).toISOString();
    expect(screen.getByText(firstExpected)).toBeInTheDocument();
    expect(screen.getByText(lastExpected)).toBeInTheDocument();
  });

  it("shows evidence pack warning when chain is broken", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/health") {
        return Promise.resolve(mockResponse({ status: "ok", version: "1" }));
      }
      if (url === "/api/v1/sessions") {
        return Promise.resolve(
          mockResponse({
            sessions: [
              {
                session_id: "sess-broken",
                event_count: 1,
                last_event_type: "decision",
                last_timestamp: 1712345600,
                agent_id: "agent-x",
                integrity: "broken",
              },
            ],
          }),
        );
      }
      if (url === "/api/v1/sessions/sess-broken") {
        return Promise.resolve(
          mockResponse({
            session_id: "sess-broken",
            event_count: 1,
            integrity: "broken",
            events: [
              {
                event_id: "evt-1",
                session_id: "sess-broken",
                sequence: 0,
                timestamp: 1712345600,
                event_type: "decision",
                agent_id: "agent-x",
                prompt_version: "v1.0",
                prev_hash: "",
                hash: "",
              },
            ],
          }),
        );
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(ComplianceView);

    const evidenceCard = findCard("Evidence Pack");
    await waitFor(() => {
      expect(evidenceCard.textContent).toContain("sess-broken");
    });

    const evidenceSelect = evidenceCard.querySelector("select")!;
    fireEvent.change(evidenceSelect, { target: { value: "sess-broken" } });

    fireEvent.click(screen.getByText("Generate Evidence Pack"));

    await waitFor(() => {
      expect(
        screen.getByText(/⚠ Evidence Pack \(Chain Broken\)/),
      ).toBeInTheDocument();
    });

    // hash_count should be 0 (no event has a hash)
    expect(evidenceCard.textContent).toContain("0");
  });

  it("shows evidence error when fetchSessionDetail fails", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/health") {
        return Promise.resolve(mockResponse({ status: "ok", version: "1" }));
      }
      if (url === "/api/v1/sessions") {
        return Promise.resolve(
          mockResponse({
            sessions: [
              {
                session_id: "sess-fail",
                event_count: 1,
                last_event_type: "decision",
                last_timestamp: 1712345600,
                agent_id: "agent-a",
                integrity: "ok",
              },
            ],
          }),
        );
      }
      if (url === "/api/v1/sessions/sess-fail") {
        return Promise.reject(new Error("Session detail unavailable"));
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(ComplianceView);

    const evidenceCard = findCard("Evidence Pack");
    await waitFor(() => {
      expect(evidenceCard.textContent).toContain("sess-fail");
    });

    const evidenceSelect = evidenceCard.querySelector("select")!;
    fireEvent.change(evidenceSelect, { target: { value: "sess-fail" } });

    fireEvent.click(screen.getByText("Generate Evidence Pack"));

    await waitFor(() => {
      expect(
        screen.getByText(/Error: Session detail unavailable/),
      ).toBeInTheDocument();
    });
  });

  it("disables Generate Evidence Pack button while loading", async () => {
    let resolveDetail: (v: unknown) => void;
    const detailPromise = new Promise((resolve) => {
      resolveDetail = resolve;
    });

    mockFetch.mockImplementation((url: string) => {
      if (url === "/health") {
        return Promise.resolve(mockResponse({ status: "ok", version: "1" }));
      }
      if (url === "/api/v1/sessions") {
        return Promise.resolve(
          mockResponse({
            sessions: [
              {
                session_id: "sess-slow",
                event_count: 1,
                last_event_type: "decision",
                last_timestamp: 1712345600,
                agent_id: "agent-a",
                integrity: "ok",
              },
            ],
          }),
        );
      }
      if (url === "/api/v1/sessions/sess-slow") {
        return detailPromise;
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(ComplianceView);

    const evidenceCard = findCard("Evidence Pack");
    await waitFor(() => {
      expect(evidenceCard.textContent).toContain("sess-slow");
    });

    const evidenceSelect = evidenceCard.querySelector("select")!;
    fireEvent.change(evidenceSelect, { target: { value: "sess-slow" } });

    fireEvent.click(screen.getByText("Generate Evidence Pack"));

    expect(screen.getByText("Generating…")).toBeDisabled();

    resolveDetail!(
      mockResponse({
        session_id: "sess-slow",
        event_count: 1,
        integrity: "ok",
        events: [
          {
            event_id: "evt-1",
            session_id: "sess-slow",
            sequence: 0,
            timestamp: 1712345600,
            event_type: "decision",
            agent_id: "agent-a",
            prompt_version: "v1.0",
            prev_hash: "",
            hash: "0xabc",
          },
        ],
      }),
    );

    await waitFor(() => {
      expect(screen.getByText("✓ Evidence Pack Ready")).toBeInTheDocument();
    });

    expect(screen.getByText("Generate Evidence Pack")).not.toBeDisabled();
  });

  it("shows evidence pack with N/A timestamps when session has no events", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/health") {
        return Promise.resolve(mockResponse({ status: "ok", version: "1" }));
      }
      if (url === "/api/v1/sessions") {
        return Promise.resolve(
          mockResponse({
            sessions: [
              {
                session_id: "sess-empty-events",
                event_count: 0,
                last_event_type: "decision",
                last_timestamp: 1712345600,
                agent_id: "agent-a",
                integrity: "ok",
              },
            ],
          }),
        );
      }
      if (url === "/api/v1/sessions/sess-empty-events") {
        return Promise.resolve(
          mockResponse({
            session_id: "sess-empty-events",
            event_count: 0,
            integrity: "ok",
            events: [],
          }),
        );
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    render(ComplianceView);

    const evidenceCard = findCard("Evidence Pack");
    await waitFor(() => {
      expect(evidenceCard.textContent).toContain("sess-empty-events");
    });

    const evidenceSelect = evidenceCard.querySelector("select")!;
    fireEvent.change(evidenceSelect, { target: { value: "sess-empty-events" } });

    fireEvent.click(screen.getByText("Generate Evidence Pack"));

    await waitFor(() => {
      expect(screen.getByText("✓ Evidence Pack Ready")).toBeInTheDocument();
    });

    // Empty events → timestamps should be "N/A"
    expect(evidenceCard.textContent).toContain("0"); // event_count
    expect(evidenceCard.textContent).toContain("N/A");

    // No event types section when events is empty
    const eventTypesSection = evidenceCard.querySelector(".evidence-section h3");
    expect(eventTypesSection).not.toBeInTheDocument();
  });
});
