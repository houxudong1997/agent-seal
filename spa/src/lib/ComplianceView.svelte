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

  let health: HealthResponse | null = $state(null);
  let healthLoading = $state(true);

  let sessions: SessionSummary[] = $state([]);
  let sessionsLoading = $state(true);

  let verifying = $state(false);
  let verifyResult: VerifyResponse | null = $state(null);
  let verifyError: string | null = $state(null);
  let selectedSessionId: string = $state("");

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
    verifying = true;
    verifyError = null;
    try {
      verifyResult = await verifyChain();
    } catch (e) {
      verifyError = String(e);
      verifyResult = null;
    } finally {
      verifying = false;
    }
  }

  async function handleVerifySession() {
    if (!selectedSessionId) return;
    verifying = true;
    verifyError = null;
    try {
      verifyResult = await verifyChain(selectedSessionId);
    } catch (e) {
      verifyError = String(e);
      verifyResult = null;
    } finally {
      verifying = false;
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
  <!-- Left column -->
  <div class="col">
    <!-- Health Status -->
    <div class="glass-card">
      <div class="card-head">
        <div class="card-title-group">
          <h2>Health Status</h2>
          <span class="status-dot" class:ok={health?.status === "ok"}></span>
        </div>
        <button class="btn btn-ghost" onclick={loadHealth}>Refresh</button>
      </div>
      {#if healthLoading}
        <div class="empty-state"><div class="empty-pulse"></div><p>Checking...</p></div>
      {:else if health}
        <div class="health-detail">
          <div class="health-row">
            <span class="health-label">API Status</span>
            <span class="status-badge-ok">{health.status}</span>
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
    <div class="glass-card">
      <div class="card-head">
        <h2>Chain Verification</h2>
      </div>
      <p class="card-desc">
        Verify the cryptographic hash chain integrity across all sessions or a specific session.
      </p>

      <div class="verify-actions">
        <button class="btn btn-primary" onclick={handleVerifyAll} disabled={verifying}>
          {verifying ? "Verifying..." : "Verify All Sessions"}
        </button>
      </div>

      <div class="verify-single">
        <select bind:value={selectedSessionId} class="select-glass">
          <option value="">-- Select a session --</option>
          {#each sessions as s (s.session_id)}
            <option value={s.session_id}>{s.session_id}</option>
          {/each}
        </select>
        <button class="btn" onclick={handleVerifySession} disabled={verifying || !selectedSessionId}>
          Verify
        </button>
      </div>

      {#if verifyError}
        <div class="result result-error">
          <p>Error: {verifyError}</p>
        </div>
      {/if}

      {#if verifyResult}
        <div class="result {verifyResult.integrity === 'ok' ? 'result-ok' : 'result-broken'}">
          <div class="result-header">
            <span class="result-icon">{verifyResult.integrity === "ok" ? "✓" : "✗"}</span>
            <span>{verifyResult.integrity === "ok" ? "All Chains Intact" : "Chain(s) Broken"}</span>
          </div>
          {#if verifyResult.sessions}
            <div class="result-sessions">
              {#each Object.entries(verifyResult.sessions) as [sid, status]}
                <div class="result-session-row">
                  <span class="mono sid-text">{sid}</span>
                  <span class="integrity-badge" class:badge-ok={status === "ok"} class:badge-broken={status !== "ok"}>
                    {status}
                  </span>
                </div>
              {/each}
            </div>
          {:else if verifyResult.session_id}
            <p class="result-single">Session {verifyResult.session_id}: <strong>{verifyResult.integrity}</strong></p>
          {/if}
        </div>
      {/if}
    </div>
  </div>

  <!-- Right column -->
  <div class="col">
    <!-- Prompt Versions -->
    <div class="glass-card">
      <div class="card-head">
        <h2>Prompt Versions</h2>
      </div>
      <p class="card-desc">
        Track prompt versions used across sessions. Each event records the prompt version active at the time of the agent decision.
      </p>
      {#if sessionsLoading}
        <div class="empty-state"><div class="empty-pulse"></div><p>Loading...</p></div>
      {:else if sessions.length > 0}
        <div class="prompt-list">
          {#each sessions as s (s.session_id)}
            <div class="prompt-row">
              <span class="mono prompt-sid">{s.session_id}</span>
              <span class="prompt-type">{s.last_event_type}</span>
            </div>
          {/each}
        </div>
      {:else}
        <p class="empty-state">No sessions available</p>
      {/if}
    </div>

    <!-- Evidence Pack -->
    <div class="glass-card">
      <div class="card-head">
        <h2>Evidence Pack</h2>
      </div>
      <p class="card-desc">
        Generate a compliance evidence pack for a session — includes chain validation, event timeline, and agent prompt version history.
      </p>

      <div class="evidence-form">
        <select bind:value={evidenceSessionId} class="select-glass">
          <option value="">-- Select session --</option>
          {#each sessions as s (s.session_id)}
            <option value={s.session_id}>{s.session_id}</option>
          {/each}
        </select>
        <button class="btn btn-primary" onclick={handleGenerateEvidence} disabled={evidenceLoading || !evidenceSessionId}>
          {evidenceLoading ? "Generating..." : "Generate"}
        </button>
      </div>

      {#if evidenceError}
        <div class="result result-error">
          <p>Error: {evidenceError}</p>
        </div>
      {/if}

      {#if evidencePack}
        <div class="result {evidencePack.chain_valid ? 'result-ok' : 'result-warn'}">
          <div class="result-header">
            <span class="result-icon">{evidencePack.chain_valid ? "✓" : "⚠"}</span>
            <span>{evidencePack.chain_valid ? "Evidence Pack Ready" : "Chain Broken"}</span>
          </div>
          <div class="evidence-grid">
            <div class="evidence-field">
              <span class="field-label">Session</span>
              <span class="mono">{evidencePack.session_id}</span>
            </div>
            <div class="evidence-field">
              <span class="field-label">Events</span>
              <span>{evidencePack.event_count}</span>
            </div>
            <div class="evidence-field">
              <span class="field-label">Integrity</span>
              <span class="integrity-badge" class:badge-ok={evidencePack.chain_valid} class:badge-broken={!evidencePack.chain_valid}>
                {evidencePack.integrity}
              </span>
            </div>
            <div class="evidence-field">
              <span class="field-label">Hash Count</span>
              <span>{evidencePack.hash_count}</span>
            </div>
            <div class="evidence-field span-2">
              <span class="field-label">Period</span>
              <span class="mono period">{evidencePack.first_event_time} — {evidencePack.last_event_time}</span>
            </div>
          </div>

          {#if Object.keys(evidencePack.event_types).length > 0}
            <div class="evidence-section">
              <h3>Event Types</h3>
              <div class="type-chips">
                {#each Object.entries(evidencePack.event_types) as [type, count]}
                  <span class="type-chip">
                    <span class="event-type-badge type-{type}">{type}</span>
                    <span class="chip-count">{count}</span>
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

  .glass-card {
    background: var(--glass);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-lg);
    padding: 22px;
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

  .card-title-group {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .card-head h2 {
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--text-bright);
    letter-spacing: -0.01em;
  }

  .card-desc {
    font-size: 0.8rem;
    color: var(--dim);
    margin-bottom: 16px;
    line-height: 1.55;
  }

  .status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--dim);
  }
  .status-dot.ok {
    background: var(--green);
    box-shadow: 0 0 6px var(--green);
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
    padding: 10px 14px;
    background: rgba(0, 0, 0, 0.15);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius);
  }

  .health-label {
    font-size: 0.78rem;
    color: var(--dim);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .status-badge-ok {
    display: inline-block;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 20px;
    background: rgba(52, 211, 153, 0.1);
    color: var(--green);
    border: 1px solid rgba(52, 211, 153, 0.12);
  }

  .verify-actions {
    margin-bottom: 12px;
  }

  .verify-single {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
  }

  .select-glass {
    flex: 1;
    padding: 10px 14px;
    background: var(--glass-alt);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius);
    color: var(--text);
    font-size: 0.8rem;
    font-family: var(--font);
    outline: none;
    cursor: pointer;
    transition: border-color var(--transition);
  }

  .select-glass:focus {
    border-color: var(--glass-border-active);
    box-shadow: 0 0 12px rgba(245, 158, 11, 0.04);
  }

  .evidence-form {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
  }

  .result {
    margin-top: 12px;
    padding: 18px;
    border-radius: var(--radius);
    border: 1px solid;
    background: rgba(0, 0, 0, 0.1);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
  }

  .result-ok {
    border-color: rgba(52, 211, 153, 0.2);
    box-shadow: inset 0 0 20px rgba(52, 211, 153, 0.02);
  }
  .result-ok .result-header { color: var(--green); }

  .result-broken {
    border-color: rgba(248, 113, 113, 0.2);
    box-shadow: inset 0 0 20px rgba(248, 113, 113, 0.02);
  }
  .result-broken .result-header { color: var(--red); }

  .result-warn {
    border-color: rgba(245, 158, 11, 0.2);
    box-shadow: inset 0 0 20px rgba(245, 158, 11, 0.02);
  }
  .result-warn .result-header { color: var(--amber); }

  .result-error {
    background: rgba(248, 113, 113, 0.04);
    border-color: rgba(248, 113, 113, 0.2);
    color: var(--red);
  }

  .result-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
    font-weight: 600;
    font-size: 0.85rem;
  }

  .result-icon {
    font-size: 1.1rem;
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
    background: rgba(0, 0, 0, 0.1);
    border-radius: var(--radius-sm);
  }

  .sid-text {
    font-size: 0.72rem;
    word-break: break-all;
  }

  .result-single {
    font-size: 0.82rem;
  }

  .prompt-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .prompt-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: rgba(0, 0, 0, 0.1);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-sm);
  }

  .prompt-sid {
    font-size: 0.75rem;
    word-break: break-all;
  }

  .prompt-type {
    font-size: 0.7rem;
    color: var(--dim);
    flex-shrink: 0;
    margin-left: 8px;
  }

  .evidence-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }

  .evidence-field {
    padding: 8px 12px;
    background: rgba(0, 0, 0, 0.1);
    border-radius: var(--radius-sm);
  }

  .evidence-field.span-2 {
    grid-column: 1 / -1;
  }

  .field-label {
    display: block;
    font-size: 0.6rem;
    color: var(--dim);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 2px;
  }

  .period {
    font-size: 0.7rem;
    word-break: break-all;
  }

  .evidence-section {
    margin-top: 14px;
  }

  .evidence-section h3 {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--dim);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 8px;
  }

  .type-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .type-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }

  .chip-count {
    font-size: 0.72rem;
    color: var(--dim);
    font-variant-numeric: tabular-nums;
  }

  .chip-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .chip {
    display: inline-block;
    font-size: 0.7rem;
    font-weight: 500;
    padding: 4px 10px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--glass-border);
    border-radius: 20px;
    color: var(--text);
  }

  .version-chip {
    font-family: var(--font-mono);
    font-size: 0.68rem;
  }

  .integrity-badge {
    display: inline-block;
    font-size: 0.62rem;
    font-weight: 600;
    padding: 2px 8px;
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

  .event-type-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 0.65rem;
    font-weight: 600;
    padding: 2px 8px;
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

  .btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
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

  .btn-primary:disabled {
    background: rgba(245, 158, 11, 0.05);
    border-color: rgba(245, 158, 11, 0.08);
  }

  .empty-state {
    text-align: center;
    color: var(--dim);
    padding: 32px 20px;
    font-size: 0.82rem;
  }

  .empty-pulse {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: 2px solid rgba(255, 255, 255, 0.04);
    border-top-color: var(--amber);
    animation: spin 1s linear infinite;
    margin: 0 auto 8px;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  .mono {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
  }

  @media (max-width: 800px) {
    .compliance-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
