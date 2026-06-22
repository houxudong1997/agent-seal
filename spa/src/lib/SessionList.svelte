<script lang="ts">
  import { fetchSessions, fetchSessionDetail, type SessionSummary, type SessionDetail, type EventRecord } from "./api";

  let sessions: SessionSummary[] = $state([]);
  let loading = $state(true);
  let selectedSession: SessionDetail | null = $state(null);
  let selectedDetailLoading = $state(false);

  $effect(() => {
    load();
  });

  async function load() {
    loading = true;
    try {
      const data = await fetchSessions();
      sessions = data.sessions || [];
    } catch {
      sessions = [];
    } finally {
      loading = false;
    }
  }

  async function selectSession(sessionId: string) {
    selectedDetailLoading = true;
    try {
      selectedSession = await fetchSessionDetail(sessionId);
    } catch {
      selectedSession = null;
    } finally {
      selectedDetailLoading = false;
    }
  }

  function closeDetail() {
    selectedSession = null;
  }

  function formatTime(ts: number): string {
    return new Date(ts * 1000).toLocaleString();
  }

  function integrityBadge(integrity: string): string {
    return integrity === "ok" ? "badge-ok" : "badge-broken";
  }

  function integrityLabel(integrity: string): string {
    return integrity === "ok" ? "Intact" : "Broken";
  }
</script>

<div class="tab-content">
  <div class="card">
    <div class="card-header">
      <h2>Sessions</h2>
      <button class="btn btn-sm" onclick={load}>Refresh</button>
    </div>

    {#if loading}
      <p class="empty-state">Loading…</p>
    {:else if sessions.length === 0}
      <p class="empty-state">No sessions recorded yet</p>
    {:else}
      <div class="sessions-list">
        {#each sessions as session (session.session_id)}
          <div
            class="session-card"
            class:selected={selectedSession?.session_id === session.session_id}
            onclick={() => selectSession(session.session_id)}
            onkeydown={(e: KeyboardEvent) => e.key === "Enter" && selectSession(session.session_id)}
            role="button"
            tabindex="0"
          >
            <div class="session-main">
              <div class="session-id">{session.session_id}</div>
              <div class="session-meta">
                {session.event_count} events · Last: {session.last_event_type} ·
                Agent: {session.agent_id}
              </div>
            </div>
            <div class="session-right">
              <span class="badge {integrityBadge(session.integrity)}">
                {integrityLabel(session.integrity)}
              </span>
              <span class="session-time">{formatTime(session.last_timestamp)}</span>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>

  {#if selectedDetailLoading}
    <div class="card">
      <p class="empty-state">Loading session detail…</p>
    </div>
  {:else if selectedSession}
    <div class="card detail-card">
      <div class="card-header">
        <h2>Session: {selectedSession.session_id}</h2>
        <button class="btn btn-sm" onclick={closeDetail}>✕ Close</button>
      </div>
      <div class="detail-summary">
        <span>
          <strong>{selectedSession.event_count}</strong> events
        </span>
        <span class="badge {integrityBadge(selectedSession.integrity)}">
          Chain: {integrityLabel(selectedSession.integrity)}
        </span>
      </div>

      {#if selectedSession.events.length > 0}
        <div class="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Seq</th>
                <th>Time</th>
                <th>Type</th>
                <th>Agent</th>
                <th>Event ID</th>
                <th>Hash</th>
              </tr>
            </thead>
            <tbody>
              {#each selectedSession.events as event (event.event_id)}
                <tr>
                  <td>{event.sequence}</td>
                  <td class="mono">{new Date(event.timestamp * 1000).toLocaleTimeString()}</td>
                  <td><span class="badge badge-type type-{event.event_type}">{event.event_type}</span></td>
                  <td class="truncate">{event.agent_id}</td>
                  <td class="mono">{event.event_id}</td>
                  <td class="mono">{event.hash.slice(0, 12)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
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

  .sessions-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .session-card {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    cursor: pointer;
    transition: all var(--transition);
  }

  .session-card:hover {
    border-color: var(--cyan);
    background: var(--card-hover);
  }

  .session-card.selected {
    border-color: var(--cyan);
    background: rgba(57, 210, 192, 0.06);
  }

  .session-main {
    flex: 1;
    min-width: 0;
  }

  .session-id {
    font-family: "SF Mono", "Fira Code", monospace;
    font-size: 0.85rem;
  }

  .session-meta {
    font-size: 0.75rem;
    color: var(--dim);
    margin-top: 2px;
  }

  .session-right {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 4px;
    flex-shrink: 0;
  }

  .session-time {
    font-size: 0.7rem;
    color: var(--dim);
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

  .badge-ok {
    background: rgba(46, 160, 67, 0.15);
    color: var(--green);
  }

  .badge-broken {
    background: rgba(218, 54, 51, 0.15);
    color: var(--red);
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

  .detail-summary {
    display: flex;
    gap: 12px;
    align-items: center;
    margin-bottom: 16px;
    font-size: 0.85rem;
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
</style>
