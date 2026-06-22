<script lang="ts">
  import { fetchEvents, type EventRecord } from "./api";

  interface Props {
    liveEvents: EventRecord[];
  }

  let { liveEvents }: Props = $props();

  let historicalEvents: EventRecord[] = $state([]);
  let loading = $state(true);
  let searchTerm = $state("");
  let typeFilter = $state("");
  let showSearch = $state(false);

  $effect(() => {
    loadEvents();
  });

  async function loadEvents(params: Record<string, string> = {}) {
    loading = true;
    try {
      const query: Record<string, string> = {};
      if (params?.session_id) query.session_id = params.session_id;
      if (params?.event_type) query.event_type = params.event_type;
      const data = await fetchEvents({ ...query, limit: 200 });
      historicalEvents = data.events;
    } catch {
      // Silently handle
    } finally {
      loading = false;
    }
  }

  async function handleSearch() {
    const params: Record<string, string> = {};
    if (typeFilter) params.event_type = typeFilter;
    if (searchTerm) params.session_id = searchTerm;
    await loadEvents(params);
  }

  function formatTime(ts: number): string {
    return new Date(ts * 1000).toLocaleTimeString("en-US", { hour12: false });
  }

  function formatDate(ts: number): string {
    return new Date(ts * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }

  // Combined: live events come first, then deduplicate with historical
  let allEvents = $derived.by(() => {
    const seen = new Set<string>();
    const result: EventRecord[] = [];

    // Live events first (newest)
    for (const e of [...liveEvents].reverse()) {
      if (!seen.has(e.event_id)) {
        seen.add(e.event_id);
        result.push(e);
      }
    }

    // Then historical (deduplicated)
    for (const e of historicalEvents) {
      if (!seen.has(e.event_id)) {
        seen.add(e.event_id);
        result.push(e);
      }
    }

    return result;
  });

  const eventTypes = $derived([...new Set(allEvents.map((e) => e.event_type))]);

  // ── Expand/collapse state ──────────────────────────────────────────
  let expandedEventId: string | null = $state(null);
  let expandedSections: Record<string, boolean> = $state({});

  function toggleExpand(event: EventRecord) {
    if (expandedEventId === event.event_id) {
      expandedEventId = null;
      expandedSections = {};
    } else {
      expandedEventId = event.event_id;
      expandedSections = {};
    }
  }

  function toggleSection(key: string) {
    expandedSections = { ...expandedSections, [key]: !expandedSections[key] };
  }

  function isExpanded(key: string): boolean {
    return !!expandedSections[key];
  }

  function formatAgentId(id: string): string {
    if (!id || id === "unknown") return "Unknown Agent";
    return id;
  }

  function formatSessionId(id: string): string {
    if (!id) return "--";
    return id;
  }

  function shortenEventId(id: string): string {
    if (!id) return "--";
    const parts = id.split("-");
    if (parts.length >= 2) {
      return parts[0].slice(0, 8) + "…" + parts[parts.length - 1];
    }
    return id.slice(0, 12);
  }

  // ── Content extraction helpers ──────────────────────────────────────

  /** Truncate text to maxLen, breaking at word boundary if possible. */
  function truncateText(text: string, maxLen: number): string {
    if (!text) return "";
    if (text.length <= maxLen) return text;
    return text.slice(0, maxLen) + "…";
  }

  /** Extract model name from event metadata or prompt_version. */
  function extractModel(event: EventRecord): string {
    if (event.metadata?.model && typeof event.metadata.model === "string") {
      const m = event.metadata.model;
      if (m && m !== "?" && m !== "unknown" && m.length > 1) return m;
    }
    if (event.prompt_version && event.prompt_version !== "v0" && event.prompt_version !== "?") {
      return event.prompt_version;
    }
    return "";
  }

  /** Extract duration in ms from metadata. */
  function extractDurationMs(event: EventRecord): number | null {
    if (event.metadata?.ms !== undefined) {
      const v = Number(event.metadata.ms);
      return Number.isFinite(v) ? v : null;
    }
    if (event.metadata?.elapsed_ms !== undefined) {
      const v = Number(event.metadata.elapsed_ms);
      return Number.isFinite(v) ? v : null;
    }
    return null;
  }

  /** Extract error message from event. */
  function extractError(event: EventRecord): string {
    if (event.metadata?.error && typeof event.metadata.error === "string") {
      return event.metadata.error;
    }
    if (event.output_snapshot) {
      const m = event.output_snapshot.match(/^(ERROR:?\s*)?(.+)/);
      if (m) return m[2].slice(0, 200);
    }
    return "";
  }

  /** Build a compact summary string for the table Summary column. */
  function eventSummary(event: EventRecord): { text: string; hasContent: boolean } {
    const et = event.event_type;

    // LLM request: show prompt preview + model + duration
    if (et === "llm_request") {
      const prompt = smartPreview(event.input_snapshot || "", 60);
      const model = extractModel(event);
      const duration = extractDurationMs(event);
      const parts: string[] = [];
      if (prompt) parts.push(prompt);
      if (model) parts.push(model);
      if (duration !== null) parts.push(`${duration}ms`);
      return { text: parts.join(" · ") || "(empty request)", hasContent: !!prompt };
    }

    // LLM error: show error
    if (et === "llm_error") {
      const err = extractError(event);
      return { text: err ? `⚠ ${truncateText(err, 80)}` : "⚠ LLM error", hasContent: !!err };
    }

    // observe: show function name + elapsed
    if (et === "observe") {
      const input = smartPreview(event.input_snapshot || "", 50);
      const duration = extractDurationMs(event);
      const parts: string[] = [event.agent_id];
      if (input) parts.push(input);
      if (duration !== null) parts.push(`${duration}ms`);
      return { text: parts.join(" · "), hasContent: !!event.input_snapshot };
    }

    // observe_error: show error
    if (et === "observe_error") {
      const err = extractError(event);
      return { text: err ? `⚠ ${truncateText(err, 60)}` : "⚠ Error", hasContent: !!err };
    }

    // error type: show error
    if (et === "error") {
      const err = extractError(event);
      return { text: err ? `⚠ ${truncateText(err, 80)}` : "⚠ Error", hasContent: !!err };
    }

    // Generic: show input snapshot preview
    if (event.input_snapshot) {
      return { text: smartPreview(event.input_snapshot, 80), hasContent: true };
    }
    if (event.output_snapshot) {
      return { text: smartPreview(event.output_snapshot, 80), hasContent: true };
    }
    return { text: "(no content)", hasContent: false };
  }

  /** Format duration for display. */
  function formatDuration(ms: number | null): string {
    if (ms === null) return "";
    if (ms < 1000) return `${Math.round(ms)}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  }

  /** Check if event has any expandable content. */
  function hasContent(event: EventRecord): boolean {
    return !!(
      event.input_snapshot ||
      event.output_snapshot ||
      (event.metadata && Object.keys(event.metadata).length > 0)
    );
  }

  /** Pretty-print JSON safely. */
  function prettyJson(obj: unknown): string {
    try {
      return JSON.stringify(obj, null, 2);
    } catch {
      return String(obj);
    }
  }

  /** Extract human-readable preview from raw input_snapshot (often JSON-wrapped). */
  function smartPreview(raw: string, maxLen: number): string {
    if (!raw) return "";
    // Try parse as JSON, extract meaningful fields
    try {
      const obj = JSON.parse(raw);
      // LLM API request: {"messages": [{"role":"user","content":"..."}]}
      if (obj.messages && Array.isArray(obj.messages)) {
        const userMsg = obj.messages.find((m: any) => m.role === "user");
        if (userMsg?.content) return truncateText(String(userMsg.content), maxLen);
      }
      // Terminal output: {"output": "...", "exit_code": 0}
      if (typeof obj.output === "string") {
        const out = obj.output;
        // Skip garbled output (high density of U+FFFD replacement chars)
        const garbled = (out.match(/�/g) || []).length;
        if (garbled > 3) return `[binary output]`;
        return truncateText(out, maxLen);
      }
      // Generic content field
      if (typeof obj.content === "string") return truncateText(obj.content, maxLen);
      // Text field
      if (typeof obj.text === "string") return truncateText(obj.text, maxLen);
      // Fallback: return JSON summary
      const keys = Object.keys(obj);
      return `{${keys.join(", ")}}`;
    } catch {
      // Not JSON, use as-is
    }
    // Detect garbled raw text
    const garbled = (raw.match(/�/g) || []).length;
    if (garbled > 10) return `[binary data]`;
    return truncateText(raw, maxLen);
  }
</script>

<div class="event-view">
  <!-- Event feed card -->
  <div class="glass-card">
    <div class="card-head">
      <div class="card-title-group">
        <h2>Event Feed</h2>
        <span class="live-dot" class:active={allEvents.length > 0}></span>
      </div>
      <div class="card-actions">
        <span class="event-count">{allEvents.length} events</span>
        <button class="btn btn-ghost" onclick={() => (showSearch = !showSearch)}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
          </svg>
          {showSearch ? "Hide" : "Filters"}
        </button>
      </div>
    </div>

    {#if showSearch}
      <div class="search-bar">
        <div class="search-field">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
          </svg>
          <input
            type="text"
            placeholder="Search by session ID..."
            bind:value={searchTerm}
            onkeydown={(e: KeyboardEvent) => e.key === "Enter" && handleSearch()}
          />
        </div>
        <select bind:value={typeFilter}>
          <option value="">All types</option>
          {#each eventTypes as t}
            <option value={t}>{t}</option>
          {/each}
        </select>
        <button class="btn btn-primary" onclick={handleSearch}>Search</button>
      </div>
    {/if}

    <!-- Events table -->
    {#if loading && allEvents.length === 0}
      <div class="empty-state">
        <div class="empty-pulse"></div>
        <p>Loading events...</p>
      </div>
    {:else if allEvents.length === 0}
      <div class="empty-state">
        <p>No events yet. Waiting for activity...</p>
      </div>
    {:else}
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th class="col-time">Time</th>
              <th class="col-session">Session</th>
              <th class="col-summary">Summary</th>
              <th class="col-type">Type</th>
              <th class="col-agent">Agent</th>
              <th class="col-id">Event ID</th>
            </tr>
          </thead>
          <tbody>
            {#each allEvents as event (event.event_id)}
              {@const summary = eventSummary(event)}
              <!-- Main row -->
              <tr
                class="event-row"
                class:expanded={expandedEventId === event.event_id}
                onclick={() => toggleExpand(event)}
                data-event-id={event.event_id}
              >
                <td class="cell-time">
                  <span class="time-main">{formatTime(event.timestamp)}</span>
                  <span class="time-date">{formatDate(event.timestamp)}</span>
                </td>
                <td class="cell-session mono truncate">{formatSessionId(event.session_id)}</td>
                <td class="cell-summary">
                  <span class="summary-text" class:dim={!summary.hasContent}>
                    {summary.text}
                  </span>
                </td>
                <td>
                  <span class="event-type-badge type-{event.event_type}">
                    {event.event_type}
                  </span>
                </td>
                <td class="cell-agent">
                  {#if !event.agent_id || event.agent_id === "unknown"}
                    <span class="agent-unknown">
                      <span class="agent-dot"></span>
                      Unknown
                    </span>
                  {:else}
                    <span class="agent-name truncate">{event.agent_id}</span>
                  {/if}
                </td>
                <td class="cell-id mono">{shortenEventId(event.event_id)}</td>
              </tr>

              <!-- Expanded detail row -->
              {#if expandedEventId === event.event_id}
                <tr class="expand-row">
                  <td colspan="6">
                    <div class="expand-content">
                      <!-- Metadata chips -->
                      <div class="expand-chips">
                        {#if extractModel(event)}
                          <span class="chip chip-model" title="Model">
                            {extractModel(event)}
                          </span>
                        {/if}
                        {#if extractDurationMs(event) !== null}
                          <span class="chip chip-duration" title="Duration">
                            {formatDuration(extractDurationMs(event))}
                          </span>
                        {/if}
                        <span class="chip chip-seq" title="Sequence">
                          seq #{event.sequence}
                        </span>
                        {#if event.prompt_version && event.prompt_version !== "v0" && !extractModel(event)}
                          <span class="chip" title="Prompt version">
                            {event.prompt_version}
                          </span>
                        {/if}
                        <span class="chip chip-time" title="Full timestamp">
                          {new Date(event.timestamp * 1000).toISOString()}
                        </span>
                      </div>

                      <!-- Error banner -->
                      {#if (event.event_type === "llm_error" || event.event_type === "observe_error" || event.event_type === "error") && extractError(event)}
                        <div class="expand-error">
                          <span class="error-icon">⚠</span>
                          <span class="error-text">{extractError(event)}</span>
                        </div>
                      {/if}

                      <!-- Input section -->
                      {#if event.input_snapshot}
                        <div class="expand-section">
                          <button class="section-toggle" onclick={() => toggleSection(`input-${event.event_id}`)}>
                            <span class="toggle-arrow" class:rotated={isExpanded(`input-${event.event_id}`)}>▶</span>
                            <span class="section-label">Input</span>
                            <span class="section-preview">{smartPreview(event.input_snapshot, 100)}</span>
                          </button>
                          {#if isExpanded(`input-${event.event_id}`)}
                            <pre class="section-body">{event.input_snapshot}</pre>
                          {/if}
                        </div>
                      {/if}

                      <!-- Output section -->
                      {#if event.output_snapshot}
                        <div class="expand-section">
                          <button class="section-toggle" onclick={() => toggleSection(`output-${event.event_id}`)}>
                            <span class="toggle-arrow" class:rotated={isExpanded(`output-${event.event_id}`)}>▶</span>
                            <span class="section-label">Output</span>
                            <span class="section-preview">{smartPreview(event.output_snapshot, 100)}</span>
                          </button>
                          {#if isExpanded(`output-${event.event_id}`)}
                            <pre class="section-body">{event.output_snapshot}</pre>
                          {/if}
                        </div>
                      {/if}

                      <!-- Metadata section -->
                      {#if event.metadata && Object.keys(event.metadata).length > 0}
                        <div class="expand-section">
                          <button class="section-toggle" onclick={() => toggleSection(`meta-${event.event_id}`)}>
                            <span class="toggle-arrow" class:rotated={isExpanded(`meta-${event.event_id}`)}>▶</span>
                            <span class="section-label">Metadata</span>
                            <span class="section-preview">
                              {Object.keys(event.metadata).join(", ")}
                            </span>
                          </button>
                          {#if isExpanded(`meta-${event.event_id}`)}
                            <pre class="section-body">{prettyJson(event.metadata)}</pre>
                          {/if}
                        </div>
                      {/if}

                      <!-- Full JSON -->
                      <div class="expand-section">
                        <button class="section-toggle" onclick={() => toggleSection(`full-${event.event_id}`)}>
                          <span class="toggle-arrow" class:rotated={isExpanded(`full-${event.event_id}`)}>▶</span>
                          <span class="section-label">Full Event JSON</span>
                          <span class="section-preview dim">
                            {event.event_id}
                          </span>
                        </button>
                        {#if isExpanded(`full-${event.event_id}`)}
                          <pre class="section-body">{prettyJson(event)}</pre>
                        {/if}
                      </div>

                      <!-- Hash info -->
                      <div class="expand-hashes">
                        <span class="hash-line mono" title="Current hash">
                          hash: {event.hash ? event.hash.slice(0, 16) + "…" : "--"}
                        </span>
                        <span class="hash-line mono dim" title="Previous hash">
                          ← {event.prev_hash ? event.prev_hash.slice(0, 16) + "…" : "(genesis)"}
                        </span>
                      </div>
                    </div>
                  </td>
                </tr>
              {/if}
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </div>
</div>

<style>
  .event-view {
    /* container */
  }

  .glass-card {
    background: var(--glass);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-lg);
    padding: 20px;
    margin-bottom: 16px;
    transition: border-color var(--transition);
  }

  .glass-card:hover {
    border-color: rgba(255, 255, 255, 0.06);
  }

  .card-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 14px;
  }

  .card-title-group {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .card-head h2 {
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--text-bright);
    letter-spacing: -0.01em;
  }

  .live-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--dim);
    transition: all var(--transition);
  }

  .live-dot.active {
    background: var(--green);
    box-shadow: 0 0 6px var(--green);
  }

  .card-actions {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .event-count {
    font-size: 0.72rem;
    color: var(--dim);
    font-variant-numeric: tabular-nums;
  }

  .search-bar {
    display: flex;
    gap: 8px;
    margin-bottom: 14px;
    flex-wrap: wrap;
  }

  .search-field {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 1;
    min-width: 200px;
    padding: 0 12px;
    background: var(--glass-alt);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius);
    color: var(--dim);
    transition: border-color var(--transition);
  }

  .search-field:focus-within {
    border-color: var(--glass-border-active);
  }

  .search-field input {
    flex: 1;
    padding: 9px 0;
    background: none;
    border: none;
    color: var(--text);
    font-size: 0.82rem;
    font-family: var(--font);
    outline: none;
  }

  .search-field input::placeholder {
    color: var(--dim);
  }

  .search-bar select {
    padding: 9px 12px;
    background: var(--glass-alt);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius);
    color: var(--text);
    font-size: 0.82rem;
    font-family: var(--font);
    outline: none;
    cursor: pointer;
    transition: border-color var(--transition);
    min-width: 120px;
  }

  .search-bar select:focus {
    border-color: var(--glass-border-active);
  }

  .table-scroll {
    max-height: 600px;
    overflow-y: auto;
    border-radius: var(--radius);
    border: 1px solid var(--glass-border);
    background: rgba(0, 0, 0, 0.15);
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.8rem;
  }

  th, td {
    padding: 10px 14px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
    text-align: left;
  }

  th {
    color: rgba(245, 158, 11, 0.55);
    font-weight: 600;
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    white-space: nowrap;
    background: rgba(0, 0, 0, 0.2);
    position: sticky;
    top: 0;
    z-index: 1;
    backdrop-filter: blur(12px);
  }

  .col-time { width: 90px; }
  .col-session { width: 120px; }
  .col-summary { width: auto; min-width: 160px; }
  .col-type { width: 120px; }
  .col-agent { width: 120px; }
  .col-id { width: 110px; }

  .event-row {
    transition: background var(--transition);
    cursor: pointer;
  }

  .event-row:hover td {
    background: var(--glass-hover);
  }

  .event-row.expanded td {
    background: rgba(245, 158, 11, 0.06);
    border-left: 2px solid var(--amber);
    padding-left: 12px;
  }

  .cell-time {
    white-space: nowrap;
  }

  .time-main {
    font-family: var(--font-mono);
    font-size: 0.78em;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }

  .time-date {
    display: block;
    font-size: 0.7em;
    color: var(--dim);
    margin-top: 1px;
  }

  .cell-session {
    max-width: 140px;
    font-size: 0.75em;
  }

  .cell-summary {
    max-width: 320px;
  }

  .summary-text {
    font-size: 0.78em;
    color: var(--text);
    line-height: 1.35;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .summary-text.dim {
    color: var(--dim);
    font-style: italic;
  }

  .cell-agent {
    /* agent cell */
  }

  .agent-unknown {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 0.78em;
    color: var(--dim);
    font-weight: 500;
  }

  .agent-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--dim);
    opacity: 0.4;
  }

  .agent-name {
    font-size: 0.82em;
  }

  .cell-id {
    font-size: 0.72em;
    color: var(--dim);
  }

  .mono {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
  }

  .truncate {
    max-width: 200px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }

  .empty-state {
    text-align: center;
    color: var(--dim);
    padding: 48px 20px;
    font-size: 0.85rem;
  }

  .empty-pulse {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    border: 2px solid rgba(255, 255, 255, 0.04);
    border-top-color: var(--amber);
    animation: spin 1s linear infinite;
    margin: 0 auto 12px;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  /* ── Event type badges ── */
  .event-type-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 0.7rem;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 20px;
    letter-spacing: 0.02em;
    text-transform: lowercase;
    font-family: var(--font-mono);
    white-space: nowrap;
  }

  .type-llm_request {
    background: rgba(245, 158, 11, 0.12);
    color: #FBBF24;
    border: 1px solid rgba(245, 158, 11, 0.15);
    box-shadow: 0 0 8px rgba(245, 158, 11, 0.06);
  }

  .type-tool_call {
    background: rgba(96, 165, 250, 0.1);
    color: var(--blue);
    border: 1px solid rgba(96, 165, 250, 0.12);
  }

  .type-decision {
    background: rgba(167, 139, 250, 0.1);
    color: var(--purple);
    border: 1px solid rgba(167, 139, 250, 0.12);
  }

  .type-guardrail {
    background: rgba(251, 191, 36, 0.08);
    color: #FBBF24;
    border: 1px solid rgba(251, 191, 36, 0.1);
  }

  .type-error {
    background: rgba(248, 113, 113, 0.1);
    color: var(--red);
    border: 1px solid rgba(248, 113, 113, 0.12);
  }

  .type-model_request {
    background: rgba(52, 211, 153, 0.08);
    color: var(--green);
    border: 1px solid rgba(52, 211, 153, 0.1);
  }

  /* ── New types for observe and llm ── */
  .type-observe {
    background: rgba(96, 165, 250, 0.08);
    color: var(--blue);
    border: 1px solid rgba(96, 165, 250, 0.1);
  }

  .type-observe_error {
    background: rgba(248, 113, 113, 0.08);
    color: var(--red);
    border: 1px solid rgba(248, 113, 113, 0.1);
  }

  .type-llm_error {
    background: rgba(248, 113, 113, 0.1);
    color: var(--red);
    border: 1px solid rgba(248, 113, 113, 0.12);
  }

  /* ── Buttons ── */
  .btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 7px 14px;
    border-radius: var(--radius);
    border: 1px solid var(--glass-border);
    background: var(--glass-alt);
    color: var(--text);
    cursor: pointer;
    font-size: 0.78rem;
    font-weight: 500;
    font-family: var(--font);
    transition: all var(--transition);
    white-space: nowrap;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
  }

  .btn:hover {
    border-color: rgba(255, 255, 255, 0.1);
    color: var(--text-bright);
    background: rgba(255, 255, 255, 0.05);
  }

  .btn-ghost {
    background: none;
    border-color: transparent;
    color: var(--dim);
  }

  .btn-ghost:hover {
    background: rgba(255, 255, 255, 0.03);
    color: var(--text);
  }

  .btn-primary {
    background: rgba(245, 158, 11, 0.1);
    border-color: rgba(245, 158, 11, 0.2);
    color: var(--amber-text);
  }

  .btn-primary:hover {
    background: rgba(245, 158, 11, 0.18);
    border-color: rgba(245, 158, 11, 0.3);
  }

  /* ── Expanded row ── */
  .expand-row td {
    padding: 0 !important;
    border-bottom: 1px solid rgba(245, 158, 11, 0.08);
    background: rgba(0, 0, 0, 0.12) !important;
    border-left: 2px solid var(--amber) !important;
  }

  .expand-content {
    padding: 12px 18px 16px 18px;
    animation: slideDown 0.2s ease;
  }

  @keyframes slideDown {
    from { opacity: 0; transform: translateY(-4px); }
    to { opacity: 1; transform: translateY(0); }
  }

  /* ── Chips ── */
  .expand-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 10px;
  }

  .chip {
    display: inline-flex;
    align-items: center;
    font-size: 0.68rem;
    font-family: var(--font-mono);
    padding: 2px 8px;
    border-radius: 12px;
    background: var(--glass-alt);
    border: 1px solid var(--glass-border);
    color: var(--dim);
  }

  .chip-model {
    color: #FBBF24;
    border-color: rgba(245, 158, 11, 0.15);
    background: rgba(245, 158, 11, 0.06);
  }

  .chip-duration {
    color: var(--green);
    border-color: rgba(52, 211, 153, 0.12);
    background: rgba(52, 211, 153, 0.06);
  }

  .chip-seq {
    color: var(--blue);
  }

  .chip-time {
    color: var(--dim);
    font-size: 0.64rem;
  }

  /* ── Error banner ── */
  .expand-error {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 8px 12px;
    margin-bottom: 10px;
    background: rgba(248, 113, 113, 0.06);
    border: 1px solid rgba(248, 113, 113, 0.12);
    border-radius: var(--radius);
    font-size: 0.78rem;
  }

  .error-icon {
    flex-shrink: 0;
    margin-top: 1px;
  }

  .error-text {
    color: var(--red);
    line-height: 1.4;
    word-break: break-word;
  }

  /* ── Expandable sections ── */
  .expand-section {
    margin-top: 6px;
  }

  .section-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 6px 8px;
    background: none;
    border: none;
    border-radius: var(--radius-sm);
    cursor: pointer;
    color: var(--text);
    font-family: var(--font);
    font-size: 0.78rem;
    text-align: left;
    transition: background var(--transition);
  }

  .section-toggle:hover {
    background: var(--glass-hover);
  }

  .toggle-arrow {
    font-size: 0.6rem;
    color: var(--dim);
    transition: transform 0.15s ease;
    flex-shrink: 0;
  }

  .toggle-arrow.rotated {
    transform: rotate(90deg);
  }

  .section-label {
    font-weight: 600;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--dim);
    flex-shrink: 0;
    min-width: 55px;
  }

  .section-preview {
    font-size: 0.74rem;
    color: var(--text);
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    flex: 1;
    min-width: 0;
  }

  .section-preview.dim {
    color: var(--dim);
  }

  .section-body {
    margin: 6px 0 6px 22px;
    background: rgba(0, 0, 0, 0.2);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius);
    padding: 12px;
    overflow-x: auto;
    font-size: 0.72rem;
    font-family: var(--font-mono);
    line-height: 1.55;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--text);
    max-height: 400px;
    overflow-y: auto;
  }

  /* ── Hash footer ── */
  .expand-hashes {
    display: flex;
    gap: 16px;
    margin-top: 10px;
    padding-top: 8px;
    border-top: 1px solid rgba(255, 255, 255, 0.04);
    font-size: 0.65rem;
    flex-wrap: wrap;
  }

  .hash-line {
    color: var(--text);
  }

  .hash-line.dim {
    color: var(--dim);
  }

  pre {
    background: rgba(0, 0, 0, 0.2);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius);
    padding: 16px;
    overflow-x: auto;
    font-size: 0.75rem;
    font-family: var(--font-mono);
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--text);
  }
</style>
