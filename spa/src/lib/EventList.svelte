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

  // Load initial events on mount
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
    return new Date(ts * 1000).toLocaleTimeString();
  }

  function formatDate(ts: number): string {
    return new Date(ts * 1000).toLocaleDateString();
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

  let selectedEvent: EventRecord | null = $state(null);

  function selectEvent(event: EventRecord) {
    selectedEvent = event;
  }

  function closeDetail() {
    selectedEvent = null;
  }
</script>

<div class="tab-content">
  <!-- Filters -->
  <div class="card">
    <div class="card-header">
      <h2>Event Feed</h2>
      <div class="header-actions">
        <span class="event-count">{allEvents.length} events</span>
        <button class="btn btn-sm" onclick={() => (showSearch = !showSearch)}>
          {showSearch ? "Hide Filters" : "Filters"}
        </button>
      </div>
    </div>

    {#if showSearch}
      <div class="search-bar">
        <input
          type="text"
          placeholder="Search by session ID…"
          bind:value={searchTerm}
          onkeydown={(e: KeyboardEvent) => e.key === "Enter" && handleSearch()}
        />
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
      <p class="empty-state">Loading events…</p>
    {:else if allEvents.length === 0}
      <p class="empty-state">No events yet. Waiting for activity…</p>
    {:else}
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Session</th>
              <th>Type</th>
              <th>Agent</th>
              <th>Event ID</th>
            </tr>
          </thead>
          <tbody>
            {#each allEvents as event (event.event_id)}
              <tr onclick={() => selectEvent(event)} class:selected={selectedEvent?.event_id === event.event_id}>
                <td class="mono" title={formatDate(event.timestamp) + " " + formatTime(event.timestamp)}>
                  {formatTime(event.timestamp)}
                </td>
                <td class="mono truncate">{event.session_id}</td>
                <td><span class="badge badge-type type-{event.event_type}">{event.event_type}</span></td>
                <td class="truncate">{event.agent_id}</td>
                <td class="mono">{event.event_id}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </div>

  <!-- Event detail panel -->
  {#if selectedEvent}
    <div class="card detail-card">
      <div class="card-header">
        <h2>Event Detail — {selectedEvent.event_id}</h2>
        <button class="btn btn-sm" onclick={closeDetail}>✕ Close</button>
      </div>
      <div class="detail-grid">
        <div class="detail-field">
          <span class="detail-label">Session</span>
          <span class="detail-value mono">{selectedEvent.session_id}</span>
        </div>
        <div class="detail-field">
          <span class="detail-label">Sequence</span>
          <span class="detail-value">{selectedEvent.sequence}</span>
        </div>
        <div class="detail-field">
          <span class="detail-label">Type</span>
          <span class="detail-value badge badge-type">{selectedEvent.event_type}</span>
        </div>
        <div class="detail-field">
          <span class="detail-label">Agent</span>
          <span class="detail-value">{selectedEvent.agent_id}</span>
        </div>
        <div class="detail-field">
          <span class="detail-label">Prompt Version</span>
          <span class="detail-value">{selectedEvent.prompt_version}</span>
        </div>
        <div class="detail-field">
          <span class="detail-label">Timestamp</span>
          <span class="detail-value">{new Date(selectedEvent.timestamp * 1000).toLocaleString()}</span>
        </div>
        <div class="detail-field">
          <span class="detail-label">Hash</span>
          <span class="detail-value mono">{selectedEvent.hash}</span>
        </div>
        <div class="detail-field">
          <span class="detail-label">Previous Hash</span>
          <span class="detail-value mono">{selectedEvent.prev_hash || "(genesis)"}</span>
        </div>
      </div>
      {#if selectedEvent.input_snapshot}
        <div class="detail-section">
          <h3>Input</h3>
          <pre>{selectedEvent.input_snapshot}</pre>
        </div>
      {/if}
      {#if selectedEvent.output_snapshot}
        <div class="detail-section">
          <h3>Output</h3>
          <pre>{selectedEvent.output_snapshot}</pre>
        </div>
      {/if}
      {#if selectedEvent.metadata && Object.keys(selectedEvent.metadata).length > 0}
        <div class="detail-section">
          <h3>Metadata</h3>
          <pre>{JSON.stringify(selectedEvent.metadata, null, 2)}</pre>
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .tab-content {
    /* container */
  }

  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
    margin-bottom: 16px;
  }

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
  }

  .card-header h2 {
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-bright);
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .event-count {
    font-size: 0.75rem;
    color: var(--dim);
  }

  .search-bar {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
    flex-wrap: wrap;
  }

  .search-bar input,
  .search-bar select {
    padding: 8px 12px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-size: 0.82rem;
    font-family: inherit;
    outline: none;
    transition: border-color var(--transition);
  }

  .search-bar input:focus,
  .search-bar select:focus {
    border-color: var(--cyan);
  }

  .search-bar input {
    flex: 1;
    min-width: 200px;
  }

  .search-bar input::placeholder {
    color: var(--dim);
  }

  .table-wrapper {
    max-height: 500px;
    overflow-y: auto;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
  }

  th,
  td {
    padding: 9px 12px;
    border-bottom: 1px solid var(--border);
    text-align: left;
  }

  th {
    color: var(--amber);
    font-weight: 600;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    white-space: nowrap;
  }

  tr:hover td {
    background: rgba(255, 255, 255, 0.01);
    cursor: pointer;
  }

  tr.selected td {
    background: rgba(57, 210, 192, 0.06);
  }

  tr:last-child td {
    border-bottom: none;
  }

  td.mono {
    font-family: "SF Mono", "Fira Code", monospace;
    font-size: 0.75em;
  }

  td.truncate {
    max-width: 200px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }

  .empty-state {
    text-align: center;
    color: var(--dim);
    padding: 40px 20px;
  }

  .badge {
    display: inline-block;
    font-size: 0.7rem;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: 500;
  }

  .badge-type {
    background: rgba(57, 210, 192, 0.12);
    color: var(--cyan);
  }

  .type-decision {
    color: var(--purple);
  }

  .type-tool_call {
    color: var(--blue);
  }

  .type-model_request {
    color: var(--cyan);
  }

  .type-guardrail {
    color: var(--amber);
  }

  .type-error {
    color: var(--red);
  }

  .btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--card);
    color: var(--text);
    cursor: pointer;
    font-size: 0.82rem;
    font-family: inherit;
    transition: all var(--transition);
    text-decoration: none;
    white-space: nowrap;
  }

  .btn:hover {
    border-color: var(--cyan);
    color: var(--text-bright);
  }

  .btn-primary {
    border-color: var(--cyan);
    color: var(--cyan);
  }

  .btn-primary:hover {
    background: rgba(57, 210, 192, 0.08);
  }

  .btn-sm {
    padding: 4px 10px;
    font-size: 0.75rem;
  }

  .detail-card {
    animation: slideIn 0.2s ease;
  }

  @keyframes slideIn {
    from {
      opacity: 0;
      transform: translateY(-4px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .detail-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 8px;
    margin-bottom: 16px;
  }

  .detail-field {
    padding: 8px 12px;
    background: var(--bg-secondary);
    border-radius: 6px;
  }

  .detail-label {
    display: block;
    font-size: 0.7rem;
    color: var(--dim);
    text-transform: uppercase;
    margin-bottom: 2px;
  }

  .detail-value {
    font-size: 0.82rem;
  }

  .detail-value.mono {
    font-family: "SF Mono", "Fira Code", monospace;
    font-size: 0.75em;
    word-break: break-all;
  }

  .detail-section {
    margin-top: 16px;
  }

  .detail-section h3 {
    font-size: 0.85rem;
    color: var(--text-bright);
    margin-bottom: 8px;
  }

  pre {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px;
    overflow-x: auto;
    font-size: 0.78rem;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
  }
</style>
