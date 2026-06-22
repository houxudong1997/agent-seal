<script lang="ts">
  import { fetchSessions, fetchSessionDetail, type SessionSummary, type SessionDetail } from "./api";

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

  function formatAgentId(id: string): string {
    if (!id || id === "unknown") return "Unknown";
    return id;
  }
</script>

<div class="session-view">
  <div class="glass-card">
    <div class="card-head">
      <h2>Sessions</h2>
      <button class="btn btn-ghost" onclick={load}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
          <path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
        </svg>
        Refresh
      </button>
    </div>

    {#if loading}
      <div class="empty-state">
        <div class="empty-pulse"></div>
        <p>Loading...</p>
      </div>
    {:else if sessions.length === 0}
      <p class="empty-state">No sessions recorded yet</p>
    {:else}
      <div class="sessions-list">
        {#each sessions as session (session.session_id)}
          <div
            class="session-item"
            class:selected={selectedSession?.session_id === session.session_id}
            onclick={() => selectSession(session.session_id)}
            onkeydown={(e: KeyboardEvent) => e.key === "Enter" && selectSession(session.session_id)}
            role="button"
            tabindex="0"
          >
            <div class="session-info">
              <div class="session-id">{session.session_id}</div>
              <div class="session-meta">
                <span class="meta-count">{session.event_count} events</span>
                <span class="meta-sep">·</span>
                <span class="meta-type">{session.last_event_type}</span>
                <span class="meta-sep">·</span>
                <span class="meta-agent">{formatAgentId(session.agent_id)}</span>
              </div>
            </div>
            <div class="session-extra">
              <span class="integrity-badge {integrityBadge(session.integrity)}">
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
    <div class="glass-card">
      <p class="empty-state">Loading session detail...</p>
    </div>
  {:else if selectedSession}
    <div class="glass-card detail-card">
      <div class="card-head">
        <h2>Session: {selectedSession.session_id}</h2>
        <button class="btn btn-ghost" onclick={closeDetail}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M18 6 6 18"/><path d="m6 6 12 12"/>
          </svg>
          Close
        </button>
      </div>
      <div class="detail-summary">
        <span class="summary-stat">
          <strong>{selectedSession.event_count}</strong> events
        </span>
        <span class="integrity-badge {integrityBadge(selectedSession.integrity)}">
          Chain: {integrityLabel(selectedSession.integrity)}
        </span>
      </div>

      {#if selectedSession.events.length > 0}
        <div class="table-scroll">
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
                <tr class="event-row">
                  <td class="seq-cell">#{event.sequence}</td>
                  <td class="mono">{new Date(event.timestamp * 1000).toLocaleTimeString("en-US", { hour12: false })}</td>
                  <td>
                    <span class="event-type-badge type-{event.event_type}">{event.event_type}</span>
                  </td>
                  <td class="truncate">{formatAgentId(event.agent_id)}</td>
                  <td class="mono truncate">{event.event_id}</td>
                  <td class="mono hash-cell">{event.hash.slice(0, 12)}</td>
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
  .session-view {
    /* container */
  }

  .glass-card {
    background: var(--glass);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-lg);
    padding: 22px;
    margin-bottom: 16px;
    transition: border-color var(--transition);
  }

  .glass-card:hover {
    border-color: rgba(255, 255, 255, 0.07);
  }

  .card-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 14px;
  }

  .card-head h2 {
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--text-bright);
    letter-spacing: -0.01em;
  }

  .sessions-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .session-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 14px 16px;
    background: rgba(0, 0, 0, 0.15);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius);
    cursor: pointer;
    transition: all var(--transition);
  }

  .session-item:hover {
    border-color: rgba(245, 158, 11, 0.18);
    background: rgba(245, 158, 11, 0.04);
  }

  .session-item.selected {
    border-color: rgba(245, 158, 11, 0.25);
    background: rgba(245, 158, 11, 0.06);
    box-shadow: 0 0 16px rgba(245, 158, 11, 0.03);
  }

  .session-info {
    flex: 1;
    min-width: 0;
  }

  .session-id {
    font-family: var(--font-mono);
    font-size: 0.82rem;
    color: var(--text-bright);
  }

  .session-meta {
    font-size: 0.72rem;
    color: var(--dim);
    margin-top: 3px;
    display: flex;
    gap: 5px;
    flex-wrap: wrap;
  }

  .meta-sep {
    opacity: 0.3;
  }

  .meta-count {
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }

  .session-extra {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 5px;
    flex-shrink: 0;
    margin-left: 12px;
  }

  .session-time {
    font-size: 0.68rem;
    color: var(--dim);
    white-space: nowrap;
  }

  .integrity-badge {
    display: inline-block;
    font-size: 0.65rem;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 20px;
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }

  .badge-ok {
    background: rgba(52, 211, 153, 0.1);
    color: var(--green);
    border: 1px solid rgba(52, 211, 153, 0.12);
  }

  .badge-broken {
    background: rgba(248, 113, 113, 0.1);
    color: var(--red);
    border: 1px solid rgba(248, 113, 113, 0.12);
  }

  .empty-state {
    text-align: center;
    color: var(--dim);
    padding: 48px 20px;
    font-size: 0.85rem;
  }

  .empty-pulse {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    border: 2px solid rgba(255, 255, 255, 0.04);
    border-top-color: var(--amber);
    animation: spin 1s linear infinite;
    margin: 0 auto 10px;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  .detail-card {
    animation: slideIn 0.25s ease;
  }

  @keyframes slideIn {
    from { opacity: 0; transform: translateY(-6px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .detail-summary {
    display: flex;
    gap: 12px;
    align-items: center;
    margin-bottom: 14px;
    font-size: 0.82rem;
  }

  .summary-stat {
    color: var(--dim);
  }

  .summary-stat strong {
    color: var(--text-bright);
    font-size: 1.1em;
  }

  .table-scroll {
    max-height: 480px;
    overflow-y: auto;
    border-radius: var(--radius);
    border: 1px solid var(--glass-border);
    background: rgba(0, 0, 0, 0.15);
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.78rem;
  }

  th, td {
    padding: 9px 12px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
    text-align: left;
  }

  th {
    color: rgba(245, 158, 11, 0.55);
    font-weight: 600;
    font-size: 0.62rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    white-space: nowrap;
    background: rgba(0, 0, 0, 0.25);
    position: sticky;
    top: 0;
    z-index: 1;
    backdrop-filter: blur(16px);
  }

  th::after {
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 1px;
    background: rgba(245, 158, 11, 0.08);
  }

  .event-row:last-child td {
    border-bottom: none;
  }

  .event-row:hover td {
    background: rgba(255, 255, 255, 0.02);
  }

  .seq-cell {
    font-variant-numeric: tabular-nums;
    color: var(--dim);
  }

  .hash-cell {
    color: var(--dim);
    font-size: 0.72em;
  }

  .mono {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
  }

  .truncate {
    max-width: 180px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }

  /* ── Event type badges (reuse) ── */
  .event-type-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 0.68rem;
    font-weight: 600;
    padding: 2px 9px;
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

  .btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
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
</style>
