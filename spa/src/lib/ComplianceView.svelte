<script lang="ts">
  import {
    fetchSessions,
    fetchSessionDetail,
    fetchHealth,
    verifyChain,
    type SessionSummary,
    type VerifyResponse,
    type HealthResponse,
  } from "./api";

  // Health status
  let health: HealthResponse | null = $state(null);
  let healthLoading = $state(true);

  // Session list for verification
  let sessions: SessionSummary[] = $state([]);
  let sessionsLoading = $state(true);

  // Verification state
  let verifing = $state(false);
  let verifyResult: VerifyResponse | null = $state(null);
  let verifyError: string | null = $state(null);
  let selectedSessionId: string = $state("");

  // Evidence pack state
  let evidenceSessionId: string = $state("");
  let evidenceLoading = $state(false);
  let evidencePack: {
    session_id: string;
    integrity: string;
    event_count: number;
    first_event_time: string;
    last_event_time: string;
    event_types: Record<string, number>;
    agents: string[];
    prompt_versions: string[];
    chain_valid: boolean;
    hash_count: number;
  } | null = $state(null);
  let evidenceError: string | null = $state(null);

  // Load health and sessions on mount
  $effect(() => {
    loadHealth();
    loadSessions();
  });

  async function loadHealth() {
    healthLoading = true;
    try {
      health = await fetchHealth();
    } catch {
      health = null;
    } finally {
      healthLoading = false;
    }
  }

  async function loadSessions() {
    sessionsLoading = true;
    try {
      const data = await fetchSessions();
      sessions = data.sessions || [];
    } catch {
      sessions = [];
    } finally {
      sessionsLoading = false;
    }
  }

  async function handleVerifyAll() {
    verifing = true;
    verifyError = null;
    try {
      verifyResult = await verifyChain();
    } catch (e) {
      verifyError = String(e);
      verifyResult = null;
    } finally {
      verifing = false;
    }
  }

  async function handleVerifySession() {
    if (!selectedSessionId) return;
    verifing = true;
    verifyError = null;
    try {
      verifyResult = await verifyChain(selectedSessionId);
    } catch (e) {
      verifyError = String(e);
      verifyResult = null;
    } finally {
      verifing = false;
    }
  }

  async function handleGenerateEvidence() {
    if (!evidenceSessionId) return;
    evidenceLoading = true;
    evidenceError = null;
    try {
      const detail = await fetchSessionDetail(evidenceSessionId);
      const events = detail.events;

      const eventTypes: Record<string, number> = {};
      const agents = new Set<string>();
      const promptVersions = new Set<string>();

      for (const e of events) {
        eventTypes[e.event_type] = (eventTypes[e.event_type] || 0) + 1;
        if (e.agent_id) agents.add(e.agent_id);
        if (e.prompt_version) promptVersions.add(e.prompt_version);
      }

      const timestamps = events.map((e) => e.timestamp);
      const firstTime = timestamps.length > 0 ? new Date(Math.min(...timestamps) * 1000).toISOString() : "N/A";
      const lastTime = timestamps.length > 0 ? new Date(Math.max(...timestamps) * 1000).toISOString() : "N/A";

      evidencePack = {
        session_id: detail.session_id,
        integrity: detail.integrity,
        event_count: detail.event_count,
        first_event_time: firstTime,
        last_event_time: lastTime,
        event_types: eventTypes,
        agents: [...agents],
        prompt_versions: [...promptVersions],
        chain_valid: detail.integrity === "ok",
        hash_count: events.filter((e) => e.hash).length,
      };
    } catch (e) {
      evidenceError = String(e);
      evidencePack = null;
    } finally {
      evidenceLoading = false;
    }
  }
</script>

<div class="compliance-grid">
  <!-- Left column: Health + Chain Verification -->
  <div class="col">
    <!-- Health Status -->
    <div class="card">
      <div class="card-header">
        <h2>Health Status</h2>
        <button class="btn btn-sm" onclick={loadHealth}>Refresh</button>
      </div>
      {#if healthLoading}
        <p class="empty-state">Checking…</p>
      {:else if health}
        <div class="health-detail">
          <div class="health-row">
            <span class="health-label">API Status</span>
            <span class="badge badge-ok">{health.status}</span>
          </div>
          <div class="health-row">
            <span class="health-label">Version</span>
            <span class="mono">{health.version}</span>
          </div>
        </div>
      {:else}
        <p class="empty-state error-text">Health check failed</p>
      {/if}
    </div>

    <!-- Chain Verification -->
    <div class="card">
      <div class="card-header">
        <h2>Chain Verification</h2>
      </div>
      <p class="description">
        Verify the cryptographic hash chain integrity across all sessions or a specific session.
      </p>

      <div class="verify-actions">
        <button class="btn btn-primary" onclick={handleVerifyAll} disabled={verifing}>
          {verifing ? "Verifying…" : "Verify All Sessions"}
        </button>
      </div>

      <div class="verify-single">
        <select
          bind:value={selectedSessionId}
          class="session-select"
        >
          <option value="">-- Select a session --</option>
          {#each sessions as s (s.session_id)}
            <option value={s.session_id}>{s.session_id} ({s.event_count} events, {s.integrity})</option>
          {/each}
        </select>
        <button class="btn" onclick={handleVerifySession} disabled={verifing || !selectedSessionId}>
          Verify Session
        </button>
      </div>

      {#if verifyError}
        <div class="result error">
          <p>Error: {verifyError}</p>
        </div>
      {/if}

      {#if verifyResult}
        <div class="result {verifyResult.integrity === 'ok' ? 'result-ok' : 'result-broken'}">
          <div class="result-header">
            <span class="result-badge">
              {verifyResult.integrity === "ok" ? "✓ All Chains Intact" : "✗ Chain(s) Broken"}
            </span>
          </div>
          {#if verifyResult.sessions}
            <div class="result-sessions">
              {#each Object.entries(verifyResult.sessions) as [sid, status]}
                <div class="result-session-row">
                  <span class="mono session-name">{sid}</span>
                  <span class="badge" class:badge-ok={status === "ok"} class:badge-broken={status === "broken"}>
                    {status}
                  </span>
                </div>
              {/each}
            </div>
          {:else if verifyResult.session_id}
            <p>Session {verifyResult.session_id}: <strong>{verifyResult.integrity}</strong></p>
          {/if}
        </div>
      {/if}
    </div>
  </div>

  <!-- Right column: Prompt Versions + Evidence Pack -->
  <div class="col">
    <!-- Prompt Versions -->
    <div class="card">
      <div class="card-header">
        <h2>Prompt Versions</h2>
      </div>
      <p class="description">
        Track prompt versions used across sessions. Each event records the prompt version active at the time of the agent decision.
      </p>
      {#if sessionsLoading}
        <p class="empty-state">Loading…</p>
      {:else if sessions.length > 0}
        <div class="prompt-list">
          {#each sessions as s (s.session_id)}
            <div class="prompt-row">
              <span class="mono session-name">{s.session_id}</span>
              <span class="text-dim">{s.last_event_type}</span>
            </div>
          {/each}
        </div>
      {:else}
        <p class="empty-state">No sessions available</p>
      {/if}
    </div>

    <!-- Evidence Pack -->
    <div class="card">
      <div class="card-header">
        <h2>Evidence Pack</h2>
      </div>
      <p class="description">
        Generate a compliance evidence pack for a session — includes chain validation, event timeline, and agent prompt version history.
      </p>

      <div class="evidence-form">
        <select
          bind:value={evidenceSessionId}
          class="session-select"
        >
          <option value="">-- Select session --</option>
          {#each sessions as s (s.session_id)}
            <option value={s.session_id}>{s.session_id}</option>
          {/each}
        </select>
        <button
          class="btn btn-primary"
          onclick={handleGenerateEvidence}
          disabled={evidenceLoading || !evidenceSessionId}
        >
          {evidenceLoading ? "Generating…" : "Generate Evidence Pack"}
        </button>
      </div>

      {#if evidenceError}
        <div class="result error">
          <p>Error: {evidenceError}</p>
        </div>
      {/if}

      {#if evidencePack}
        <div class="result result-ok">
          <div class="result-header">
            <span class="result-badge">
              {evidencePack.chain_valid ? "✓ Evidence Pack Ready" : "⚠ Evidence Pack (Chain Broken)"}
            </span>
          </div>
          <div class="evidence-grid">
            <div class="evidence-field">
              <span class="field-label">Session</span>
              <span class="mono">{evidencePack.session_id}</span>
            </div>
            <div class="evidence-field">
              <span class="field-label">Total Events</span>
              <span>{evidencePack.event_count}</span>
            </div>
            <div class="evidence-field">
              <span class="field-label">Chain Integrity</span>
              <span class="badge" class:badge-ok={evidencePack.chain_valid} class:badge-broken={!evidencePack.chain_valid}>
                {evidencePack.integrity}
              </span>
            </div>
            <div class="evidence-field">
              <span class="field-label">Hash Count</span>
              <span>{evidencePack.hash_count}</span>
            </div>
            <div class="evidence-field">
              <span class="field-label">First Event</span>
              <span class="mono">{evidencePack.first_event_time}</span>
            </div>
            <div class="evidence-field">
              <span class="field-label">Last Event</span>
              <span class="mono">{evidencePack.last_event_time}</span>
            </div>
          </div>

          {#if Object.keys(evidencePack.event_types).length > 0}
            <div class="evidence-section">
              <h3>Event Types</h3>
              <div class="type-chips">
                {#each Object.entries(evidencePack.event_types) as [type, count]}
                  <span class="type-chip">
                    <span class="badge badge-type type-{type}">{type}</span>
                    <span class="count">{count}</span>
                  </span>
                {/each}
              </div>
            </div>
          {/if}

          {#if evidencePack.agents.length > 0}
            <div class="evidence-section">
              <h3>Agents</h3>
              <div class="chip-list">
                {#each evidencePack.agents as agent}
                  <span class="chip">{agent}</span>
                {/each}
              </div>
            </div>
          {/if}

          {#if evidencePack.prompt_versions.length > 0}
            <div class="evidence-section">
              <h3>Prompt Versions</h3>
              <div class="chip-list">
                {#each evidencePack.prompt_versions as version}
                  <span class="chip version-chip">{version}</span>
                {/each}
              </div>
            </div>
          {/if}
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  .compliance-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    align-items: start;
  }

  .col {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
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

  .description {
    font-size: 0.82rem;
    color: var(--dim);
    margin-bottom: 16px;
    line-height: 1.5;
  }

  .health-detail {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .health-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: var(--bg-secondary);
    border-radius: 6px;
  }

  .health-label {
    font-size: 0.82rem;
    color: var(--dim);
    text-transform: uppercase;
  }

  .verify-actions {
    margin-bottom: 12px;
  }

  .verify-single {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
  }

  .session-select {
    flex: 1;
    padding: 8px 12px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-size: 0.82rem;
    font-family: inherit;
    outline: none;
  }

  .session-select:focus {
    border-color: var(--cyan);
  }

  .evidence-form {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
  }

  .result {
    margin-top: 12px;
    padding: 14px;
    border-radius: var(--radius);
    border: 1px solid;
  }

  .result-ok {
    background: rgba(46, 160, 67, 0.06);
    border-color: rgba(46, 160, 67, 0.25);
  }

  .result-broken {
    background: rgba(218, 54, 51, 0.06);
    border-color: rgba(218, 54, 51, 0.25);
  }

  .result.error {
    background: rgba(218, 54, 51, 0.06);
    border-color: var(--red);
    color: var(--red);
  }

  .result-header {
    margin-bottom: 10px;
  }

  .result-badge {
    font-weight: 600;
    font-size: 0.9rem;
  }

  .result-ok .result-badge {
    color: var(--green);
  }

  .result-broken .result-badge {
    color: var(--red);
  }

  .result-sessions {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .result-session-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6px 10px;
    background: var(--bg-secondary);
    border-radius: 4px;
  }

  .evidence-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin-bottom: 12px;
  }

  .evidence-field {
    padding: 8px 10px;
    background: var(--bg-secondary);
    border-radius: 4px;
  }

  .field-label {
    display: block;
    font-size: 0.7rem;
    color: var(--dim);
    text-transform: uppercase;
    margin-bottom: 2px;
  }

  .evidence-section {
    margin-top: 12px;
  }

  .evidence-section h3 {
    font-size: 0.8rem;
    color: var(--text-bright);
    margin-bottom: 6px;
  }

  .type-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .type-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: var(--bg-secondary);
    border-radius: 4px;
    padding: 4px 8px;
  }

  .type-chip .count {
    font-size: 0.75rem;
    color: var(--dim);
    font-weight: 600;
  }

  .chip-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .chip {
    display: inline-block;
    padding: 3px 10px;
    background: var(--bg-secondary);
    border-radius: 12px;
    font-size: 0.75rem;
    font-family: "SF Mono", "Fira Code", monospace;
  }

  .version-chip {
    color: var(--cyan);
    border: 1px solid rgba(57, 210, 192, 0.2);
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

  .prompt-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .prompt-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: var(--bg-secondary);
    border-radius: 6px;
  }

  .text-dim {
    color: var(--dim);
    font-size: 0.82rem;
  }

  .empty-state {
    text-align: center;
    color: var(--dim);
    padding: 20px;
  }

  .error-text {
    color: var(--red);
  }

  .mono {
    font-family: "SF Mono", "Fira Code", monospace;
    font-size: 0.82em;
    word-break: break-all;
  }

  .session-name {
    font-family: "SF Mono", "Fira Code", monospace;
    font-size: 0.78rem;
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

  .btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .btn-primary {
    border-color: var(--cyan);
    color: var(--cyan);
  }

  .btn-primary:hover:not(:disabled) {
    background: rgba(57, 210, 192, 0.08);
  }

  .btn-sm {
    padding: 4px 10px;
    font-size: 0.75rem;
  }

  @media (max-width: 768px) {
    .compliance-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
